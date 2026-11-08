"""OmniRoute router keys for the GPT lane runtimes: minted, probed, sealed, revoked by ID.

    python3 -I scripts/omni_keys.py status      # per runtime: store, router keys, expiry, probe
    python3 -I scripts/omni_keys.py due         # exit 0 when a runtime needs a key, else 1
    python3 -I scripts/omni_keys.py renew [RT]  # converge: mint, probe, seal, revoke old IDs

Every router call is OmniRoute 3.8.53's own CLI (`omniroute api api-keys ...`, generated from
its docs/openapi.yaml) on the loopback CLI token, so no management key exists. A minted key
is probed in memory before `keys.sh set NAME --sealed-stdin` replaces the store entry: never
argv, a plaintext file, a log or the screen. Issue #94; sources in docs/manifest.md's keys row.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / "scripts" / "keys.sh"
WITH_KEYS = ROOT / "scripts" / "with-keys.sh"
PREFIX = Path(
    os.environ.get("SEXTANT_LANE_RUNTIMES", Path.home() / ".local/share/sextant-lane-runtimes")
)
BASE_URL = "http://127.0.0.1:22128"  # #62's Sextant router port, never the old :20128-20130
# One key per runtime (#94). The store name is what the launch hook injects as OMNIROUTE_API_KEY.
RUNTIMES = {
    "pi": "OMNIROUTE_KEY_PI",
    "omp": "OMNIROUTE_KEY_OMP",
    "opencode": "OMNIROUTE_KEY_OPENCODE",
    "hermes": "OMNIROUTE_KEY_HERMES",
    "openhands": "OMNIROUTE_KEY_OPENHANDS",
    "codex": "OMNIROUTE_KEY_CODEX",
}
COMBO = "sextant-gpt"  # #62's GPT combo, the only model the runtimes name
LIFETIME = timedelta(days=30)  # #94: a bounded 30-day lifetime
# OmniRoute's own expiry alert window: src/domain/providerExpiration.ts:30, "default: 7".
RENEW_WITHIN = timedelta(days=7)
# 'cc stay native' (owner, #62): a key never reaches a Claude model, through the combo or directly.
CLAUDE = re.compile(r"claude|anthropic|opus|sonnet|haiku", re.IGNORECASE)
SEALED = "NS_SEALED_TRANSFER_COMPLETE"


class KeyError_(RuntimeError):
    """A refusal or failure whose message never carries a key value."""


def _cli(*args: str) -> object:
    """One `omniroute api ...` call with only the CLI salt injected; returns its parsed JSON."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("OMNIROUTE_API_KEY")}
    command = [
        str(WITH_KEYS),
        "--strict",
        "-k",
        "OMNIROUTE_CLI_SALT",
        "--",
        "env",
        f"DATA_DIR={PREFIX / 'router-data'}",
        f"OMNIROUTE_BASE_URL={BASE_URL}",
        "OMNIROUTE_NO_UPDATE_NOTIFIER=1",
        str(PREFIX / "router/node_modules/.bin/omniroute"),
        "api",
        *args,
        "--output",
        "json",
    ]
    out = subprocess.run(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
    )
    # The CLI prints a dotenv banner line, itself starting "[dotenv@", before its JSON, which
    # `JSON.stringify(data, null, 2)` starts with a "{" line, or a "[" or "[]" line for a list.
    lines = out.stdout.decode(errors="replace").splitlines()
    first = ("[", "[]")
    start = next((i for i, line in enumerate(lines) if line[:1] == "{" or line in first), None)
    if out.returncode != 0 or start is None:
        raise KeyError_(f"omniroute api {args[0]} {args[1]} failed (exit {out.returncode})")
    try:
        return json.loads("\n".join(lines[start:]))
    except json.JSONDecodeError as error:
        raise KeyError_(f"omniroute api {args[0]} {args[1]}: no JSON reply") from error


def router_keys() -> list[dict]:
    reply = _cli("api-keys", "get-api-keys")
    return list(reply.get("keys", [])) if isinstance(reply, dict) else []


def combo_guard() -> None:
    """Refuse to mint unless the GPT combo exists and reaches no Claude model."""
    reply = _cli("combos", "get-api-combos")
    combos = reply.get("combos", []) if isinstance(reply, dict) else []
    combo = next((c for c in combos if c.get("name") == COMBO), None)
    if combo is None or not combo.get("models"):
        raise KeyError_(f"combo {COMBO} is missing or empty; #62 owns it")
    for member in combo["models"]:
        model = str(member.get("model", ""))
        if member.get("kind") != "model" or not model or CLAUDE.search(model):
            raise KeyError_(f"combo {COMBO} reaches {model or member.get('kind')}; refusing")


def mint(runtime: str, now: datetime) -> str:
    """Create, authenticate and seal the key; returns only its router ID."""
    body = {
        "name": f"sextant-{runtime}-{now:%Y%m%dT%H%M%SZ}",
        "modelAccessMode": "restricted",
        "allowedModels": [COMBO],
        "allowedCombos": [COMBO],
        "expiresAt": (now + LIFETIME).isoformat().replace("+00:00", "Z"),
    }
    reply = _cli("api-keys", "post-api-keys", "--body", json.dumps(body))
    if not isinstance(reply, dict) or not reply.get("key") or not reply.get("id"):
        raise KeyError_(f"mint for {runtime} returned no key")
    key_id = str(reply["id"])
    value = str(reply.pop("key"))
    if not authenticates(value):
        revoke(key_id)
        raise KeyError_(f"new key {key_id} does not authenticate; stored value unchanged")
    stored = subprocess.run(
        ["bash", str(KEYS), "set", RUNTIMES[runtime], "--sealed-stdin"],
        input=f"{value}\n{SEALED}\n".encode(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if stored.returncode != 0:
        revoke(key_id)
        raise KeyError_(f"sealing {RUNTIMES[runtime]} failed; minted key {key_id} revoked")
    return key_id


def revoke(key_id: str) -> None:
    _cli("api-keys", "delete-api-keys-id-", "--id", key_id)


def stored(name: str) -> bool:
    out = subprocess.run(["bash", str(KEYS), "list"], capture_output=True, text=True, check=False)
    return any(line.split() == ["set", name] for line in out.stdout.splitlines())


def probe(name: str) -> bool:
    """The stored key, injected by with-keys into this script's `_probe`, authenticates."""
    command = [str(WITH_KEYS), "--strict", "-k", f"{name}:OMNIROUTE_PROBE_KEY", "--"]
    command += [sys.executable, "-I", str(Path(__file__).resolve()), "_probe"]
    return subprocess.run(command, capture_output=True, check=False).returncode == 0


def authenticates(value: str) -> bool:
    """Probe a key held only in memory, before it can replace the stored value."""
    # A constant loopback http URL, never a caller-supplied scheme.
    request = urllib.request.Request(f"{BASE_URL}/v1/models")  # noqa: S310
    request.add_header("Authorization", f"Bearer {value}")
    try:
        with urllib.request.urlopen(request, timeout=15) as reply:  # noqa: S310
            return reply.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def _probe() -> int:
    return 0 if authenticates(os.environ.pop("OMNIROUTE_PROBE_KEY", "")) else 1


def _expiry(key: dict) -> datetime | None:
    raw = key.get("expiresAt") or key.get("expires_at")
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None


def needs(runtime: str, keys: list[dict], now: datetime) -> str | None:
    """Why this runtime needs a new key, or None when its one key is current."""
    mine = [k for k in keys if str(k.get("name", "")).startswith(f"sextant-{runtime}-")]
    name = RUNTIMES[runtime]
    if not stored(name):
        return "not in the store"
    if len(mine) != 1:
        return f"{len(mine)} router keys, not one"
    expiry = _expiry(mine[0])
    if expiry is None or expiry - now <= RENEW_WITHIN:
        return "expires within the renewal window"
    if not probe(name):
        return "stored key does not authenticate"
    return None


def _minted_at(key: dict, runtime: str) -> datetime | None:
    """The mint time this script writes into the key's name; None for any other name."""
    try:
        stamp = str(key.get("name", "")).removeprefix(f"sextant-{runtime}-")
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def renew(runtime: str, now: datetime) -> str:
    """Converge one runtime: a fresh sealed key that authenticates, and no other key of its own.

    A run that stopped after sealing (a busy Hermes gateway, a failed revoke) is finished, not
    repeated: when the newest scripted key is sealed, current and authenticating, only the
    hand-off and the revokes run again."""
    keys = router_keys()
    reason = needs(runtime, keys, now)
    if reason is None:
        return f"{runtime}: current"
    mine = [k for k in keys if str(k.get("name", "")).startswith(f"sextant-{runtime}-")]
    oldest = datetime.min.replace(tzinfo=UTC)
    newest = max(mine, key=lambda k: _minted_at(k, runtime) or oldest, default=None)
    since = _minted_at(newest, runtime) if newest else None
    expiry = _expiry(newest) if newest else None
    if (
        len(mine) > 1
        and since is not None
        and expiry is not None
        and expiry - now > RENEW_WITHIN
        and stored(RUNTIMES[runtime])
        and probe(RUNTIMES[runtime])
    ):
        new_id = str(newest["id"])  # type: ignore[index]
        action = f"finishing {new_id}"
    else:
        combo_guard()
        new_id, since = mint(runtime, now), now
        action = f"minted {new_id}"  # mint() authenticated it in memory before sealing
    old = [str(k["id"]) for k in mine if str(k["id"]) != new_id]
    if runtime == "hermes" and old:
        hermes_handoff(since)
    for key_id in old:
        revoke(key_id)
    return f"{runtime}: {reason}; {action}, revoked {len(old)} old"


# Hermes 0.22.5 (hermes-agent@v0.22.5 bf0203a794a07aac3ff764972ab9087baa4e4f4e) runs one persistent
# gateway that keeps the key it was launched with, and each client's session keeps the credential
# it was created with ("Missing or changed credentials fail closed", website/docs/developer-guide/
# gateway-internals.md, Frozen local launch credentials). So the old key is revoked only after every
# old client is relaunched and the gateway restarted with the new one.
HERMES_HOME = PREFIX / "hermes-home"
LAUNCHER = PREFIX / "api-launch.sh"
HERMES_CLI = Path.home() / ".local/bin/hermes"  # #62's symlink to the launcher
HERMES_RESTART_WAIT = 90  # seconds; the Orca and gateway calls below each finish well inside it


def _run(*command: str) -> int:
    """One orca or hermes call; output is not shown, because neither prints a key here."""
    return subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, check=False
    ).returncode


def _process_started(pid: int) -> datetime | None:
    """A process's start from /proc/<pid>/stat field 22 and /proc/stat btime (proc(5))."""
    try:
        ticks = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
        boot = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text().splitlines()
            if line.startswith("btime ")
        )
    except (OSError, ValueError, IndexError, StopIteration):
        return None
    return datetime.fromtimestamp(boot + ticks / os.sysconf("SC_CLK_TCK"), UTC)


def hermes_clients(before: datetime) -> list[tuple[str, str]]:
    """(terminal handle, worktree id) of each Orca Hermes client started before `before`.

    Only the three public names are kept from each environment; every other entry, a key
    included, is dropped unread."""
    wanted = ("HERMES_HOME=", "ORCA_TERMINAL_HANDLE=", "ORCA_WORKTREE_ID=")
    found: dict[str, tuple[datetime, str]] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes()
            entries = (proc / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        env = dict(
            e.decode(errors="replace").split("=", 1)
            for e in entries
            if e.startswith(tuple(w.encode() for w in wanted))
        )
        if env.get("HERMES_HOME") != str(HERMES_HOME) or b"gateway" in cmdline:
            continue
        handle, worktree = env.get("ORCA_TERMINAL_HANDLE"), env.get("ORCA_WORKTREE_ID")
        started = _process_started(int(proc.name))
        if handle and worktree and started and started < before:
            found.setdefault(handle, (started, worktree))
    return [(handle, worktree) for handle, (_, worktree) in found.items()]


def hermes_gateway() -> tuple[int, datetime | None] | None:
    """The live gateway's PID and start, from Hermes's own gateway_state.json; None when stopped."""
    try:
        state = json.loads((HERMES_HOME / "gateway_state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pid = int(state.get("pid") or 0)
    if state.get("gateway_state") != "running" or pid <= 0 or not Path(f"/proc/{pid}").exists():
        return None
    return pid, _process_started(pid)


def hermes_handoff(since: datetime) -> None:
    """Relaunch old clients, restart the gateway the upstream way, all through the launcher."""
    if HERMES_CLI.resolve() != LAUNCHER.resolve():
        raise KeyError_(f"hermes: {HERMES_CLI} is not the per-runtime launcher; old kept")
    if "OMNIROUTE_KEY_HERMES" not in LAUNCHER.read_text():
        raise KeyError_(
            "hermes: the launcher does not inject OMNIROUTE_KEY_HERMES yet (#62); old kept"
        )
    for handle, worktree in hermes_clients(since):
        # `orca agent launch` starts `hermes`, which is the per-runtime launcher, so the new
        # client gets the new key from with-keys; the old pane closes only after that succeeds.
        launch = ("orca", "agent", "launch", "--agent", "hermes", "--surface", "terminal")
        if _run(*launch, "--worktree", f"id:{worktree}", "--json") != 0:
            raise KeyError_(f"hermes: relaunching client {handle} failed; old key kept")
        if _run("orca", "terminal", "close", "--terminal", handle, "--json") != 0:
            raise KeyError_(f"hermes: closing old client {handle} failed; old key kept")
    gateway = hermes_gateway()
    if gateway is None or (gateway[1] is not None and gateway[1] >= since):
        return  # stopped, or already started with the new key: the next start uses the launcher
    # `hermes gateway restart --detach`: with no service installed, the replacement starts in the
    # background with the restarting process's credentials (hermes_cli/gateway_runtime_start.py
    # spawn_unmanaged_gateway, inherit_credentials=True). Without --yes and with no terminal, it
    # refuses while turns run (website/docs/reference/cli-commands.md), so a busy gateway is retried
    # on the next run, never interrupted.
    if _run(str(HERMES_CLI), "gateway", "restart", "--detach") != 0:
        raise KeyError_("hermes: gateway restart refused (busy) or failed; old key kept")
    deadline = datetime.now(UTC) + timedelta(seconds=HERMES_RESTART_WAIT)
    while datetime.now(UTC) < deadline:
        fresh = hermes_gateway()
        if fresh and fresh[0] != gateway[0] and fresh[1] and fresh[1] >= since:
            return
        time.sleep(2)
    raise KeyError_("hermes: no restarted gateway seen; old key kept")


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "status"
    if command == "_probe":
        return _probe()
    now = datetime.now(UTC).replace(microsecond=0)
    picked = argv[1:] or list(RUNTIMES)
    if unknown := [r for r in picked if r not in RUNTIMES]:
        print(f"omni-keys: unknown runtime {unknown}", file=sys.stderr)
        return 2
    try:
        if command == "renew":
            failed = 0
            for runtime in picked:
                try:
                    print(renew(runtime, now))
                except KeyError_ as error:
                    failed = 1
                    print(f"{runtime}: {error}", file=sys.stderr)
            return failed
        keys = router_keys()
        if command == "due":
            due = [(r, why) for r in picked if (why := needs(r, keys, now))]
            for runtime, why in due:
                print(f"{runtime}: {why}")
            return 0 if due else 1
        if command == "status":
            for runtime in picked:
                mine = [k for k in keys if str(k.get("name", "")).startswith(f"sextant-{runtime}-")]
                ids = ", ".join(f"{k.get('id')} until {k.get('expiresAt')}" for k in mine) or "none"
                print(f"{runtime}: {RUNTIMES[runtime]} {needs(runtime, keys, now) or 'current'}")
                print(f"  router keys: {ids}")
            return 0
    except KeyError_ as error:
        print(f"omni-keys: {error}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
