"""`sextant-codex`: Codex CLI on OmniRoute's GPT pool, its own key and home, and its receipt."""

import hashlib
import importlib.util
import json
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[2]
RUNTIMES = ROOT / "deploy/wsl/lane-runtimes"
SPEC = importlib.util.spec_from_file_location("omni_receipt", ROOT / "scripts" / "omni_receipt.py")
assert SPEC and SPEC.loader
receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt)
KEY = "sk-omniroute-codex-fixture-that-must-never-surface"
PROMPT = "a fixture prompt that must never surface"
BEARER = "sk-router-bearer-that-must-never-surface"
EMAIL = "owner-fixture@example.com"
RUN = "0b9e3c1a-5f2d-4c7e-9a41-2d6f8e0c1b37"

# Stand-ins for the external pieces only; the launcher under test is the real script.
# with-keys.sh: injects each `-k NAME:ENV` from the fixture store, records its options, execs.
FAKE_WITH_KEYS = """#!/usr/bin/env bash
set -euo pipefail
strict=0 pairs=()
while (($#)); do
  case "$1" in
    --strict) strict=1 ;;
    -k) pairs+=("$2"); shift ;;
    --) shift; break ;;
  esac
  shift
done
printf 'strict=%s %s\\n' "$strict" "${pairs[*]}" >> "{record}/with-keys.calls"
for pair in "${pairs[@]}"; do
  IFS= read -r value < "{store}/${pair%%:*}"
  export "${pair#*:}=$value"
done
exec "$@"
"""
# codex: records its argv and what its environment holds, never the key itself.
FAKE_CODEX = """#!/usr/bin/env bash
printf '%s\\0' "$@" > "{record}/codex.argv"
{
  echo "CODEX_HOME=${CODEX_HOME-}"
  for name in ORCA_CODEX_HOME OPENAI_API_KEY OPENAI_BASE_URL OPENAI_API_BASE OPENAI_ORG_ID \\
      OPENAI_ORGANIZATION CODEX_API_KEY CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN; do
    echo "$name=${!name+set}"
  done
  echo "key_sha256=$(printf '%s' "${OMNIROUTE_API_KEY-}" | sha256sum | cut -d' ' -f1)"
  echo "ignored_signals=$(awk '/^SigIgn:/ {print $2}' /proc/$$/status)"
} > "{record}/codex.env"
exit "${FAKE_CODEX_EXIT:-0}"
"""
# omni_receipt.py: records how the launcher called it and whether it could see the key.
FAKE_RECEIPT = """import json, os, sys
from pathlib import Path
record = Path("{record}")
(record / "receipt.argv").write_text(json.dumps(sys.argv[1:]))
(record / "receipt.key").write_text("set" if "OMNIROUTE_API_KEY" in os.environ else "unset")
target = Path(sys.argv[sys.argv.index("--write") + 1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({{"run": sys.argv[1], "calls": 0}}))
"""


class Lane(SimpleNamespace):
    def run(
        self, *args: str, name: str = "sextant-codex", env: dict | None = None, cwd=None, via=None
    ):
        base = {"HOME": str(self.home), "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin"}
        return subprocess.run(
            [str(via or self.home / ".local/bin" / name), *args],
            capture_output=True,
            text=True,
            env={**base, **(env or {})},
            cwd=cwd or self.worktree,
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )

    def argv(self) -> list[str]:
        return (self.record / "codex.argv").read_bytes().decode().split("\0")[:-1]

    def env(self) -> dict[str, str]:
        lines = (self.record / "codex.env").read_text().splitlines()
        return dict(line.split("=", 1) for line in lines)

    def overrides(self) -> dict[str, object]:
        """Each `-c key=value` Codex received, its value parsed the way Codex parses it: TOML."""
        argv = self.argv()
        pairs = [argv[i + 1].split("=", 1) for i, arg in enumerate(argv) if arg == "-c"]
        return {key: tomllib.loads(f"value = {value}")["value"] for key, value in pairs}

    def sandbox_flags(self) -> list[str]:
        argv = self.argv()
        return [argv[i + 1] for i, arg in enumerate(argv) if arg == "-s"]


def _script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def lane(tmp_path: Path) -> Lane:
    """The installed layout of install.sh, with the key store, Codex and the router stubbed."""
    home, record, store = tmp_path / "home", tmp_path / "record", tmp_path / "store"
    prefix = home / ".local/share/sextant-lane-runtimes"
    repo = tmp_path / "repo"
    for path in (prefix, record, store, repo / "scripts"):
        path.mkdir(parents=True)
    shutil.copyfile(RUNTIMES / "codex-launch.sh", prefix / "codex-launch.sh")
    (prefix / "codex-launch.sh").chmod(0o755)
    for name in ("routing.json", "model-policy.json"):
        shutil.copyfile(RUNTIMES / name, prefix / name)
    (prefix / "repository-path").write_text(f"{repo}\n")
    (store / "OMNIROUTE_KEY_CODEX").write_text(f"{KEY}\n")
    fill = {"{record}": str(record), "{store}": str(store)}
    for path, body in (
        (repo / "scripts/with-keys.sh", FAKE_WITH_KEYS),
        (home / ".local/share/sextant-agents/node_modules/.bin/codex", FAKE_CODEX),
    ):
        for marker, value in fill.items():
            body = body.replace(marker, value)
        _script(path, body)
    (repo / "scripts/omni_receipt.py").write_text(FAKE_RECEIPT.format(record=record))
    # Every name install.sh links to the launcher, wherever it links it.
    installed = {}
    for where, name in re.findall(
        r'ln -sfn "\$prefix/codex-launch\.sh" "\$(HOME/\.local/bin|prefix/ao-bin)/([\w-]+)"',
        (RUNTIMES / "install.sh").read_text(),
    ):
        link = (home / ".local/bin" if where.startswith("HOME") else prefix / "ao-bin") / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(prefix / "codex-launch.sh")
        installed[f"{where.rsplit('/', 1)[-1]}/{name}"] = link
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    return Lane(
        home=home, prefix=prefix, record=record, store=store, worktree=worktree, installed=installed
    )


def test_the_codex_key_never_reaches_argv_a_file_or_a_log(lane: Lane, tmp_path: Path) -> None:
    result = lane.run(
        "exec", "--json", "Reply with one word: ready", env={"OMNIROUTE_API_KEY": "x"}
    )
    assert result.returncode == 0, result.stderr
    # One injection, by the store name, renamed to the provider's env_key, and strict.
    calls = (lane.record / "with-keys.calls").read_text().splitlines()
    assert calls == ["strict=1 OMNIROUTE_KEY_CODEX:OMNIROUTE_API_KEY"]
    # Codex holds the store's value in its environment, not an inherited one ...
    assert lane.env()["key_sha256"] == hashlib.sha256(KEY.encode()).hexdigest()
    # ... and the receipt, which runs after it, holds no key at all.
    assert (lane.record / "receipt.key").read_text() == "unset"
    assert KEY not in result.stdout + result.stderr
    for path in tmp_path.rglob("*"):
        if path.is_file() and lane.store not in path.parents:
            assert KEY.encode() not in path.read_bytes(), path


def test_codex_routes_to_the_omniroute_pool_on_the_responses_wire(lane: Lane) -> None:
    result = lane.run("exec", "--json", "Reply with one word: ready")
    assert result.returncode == 0, result.stderr
    overrides = lane.overrides()
    # OmniRoute's own launcher's provider block (launch-codex.mjs buildCodexProviderArgs) ...
    assert overrides["model_provider"] == "omniroute"
    assert overrides["model_providers.omniroute.name"] == "OmniRoute"
    assert overrides["model_providers.omniroute.base_url"] == "http://127.0.0.1:22128/v1"
    assert overrides["model_providers.omniroute.env_key"] == "OMNIROUTE_API_KEY"
    assert overrides["model_providers.omniroute.wire_api"] == "responses"
    assert overrides["model_providers.omniroute.requires_openai_auth"] is False
    # ... on the combo the runtime key is restricted to, which fails over across the pool,
    # at the owner's pinned effort, and with the release pin's update check off.
    assert overrides["model"] == "sextant-gpt"
    assert overrides["model_reasoning_effort"] == "max"
    assert overrides["check_for_update_on_startup"] is False
    # The run's id rides as the header OmniRoute records as the client session ...
    run = json.loads((lane.record / "receipt.argv").read_text())[0]
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", run)
    assert overrides["model_providers.omniroute.http_headers.session_id"] == run
    # ... and the caller's own arguments come last, unchanged.
    assert lane.argv()[-3:] == ["exec", "--json", "Reply with one word: ready"]


@pytest.mark.parametrize(
    ("name", "args", "launcher_default"),
    (
        ("sextant-codex", ("exec", "task"), ["workspace-write"]),
        ("sextant-codex-review", ("exec", "task"), ["read-only"]),
        ("sextant-codex-review", (), ["read-only"]),
        # A caller's own choice stands, as a subcommand's beats the root's in Codex.
        ("sextant-codex", ("exec", "-s", "read-only", "task"), []),
        ("sextant-codex", ("exec", "--sandbox=read-only", "task"), []),
        ("sextant-codex", ("--dangerously-bypass-approvals-and-sandbox",), []),
        ("sextant-codex", ("--yolo",), []),
        ("sextant-codex-review", ("--approve-for-me",), []),
        ("sextant-codex", ("-c", 'sandbox_mode="read-only"', "exec", "task"), []),
        # A prompt after `--` is not an option.
        ("sextant-codex", ("exec", "--", "-s"), ["workspace-write"]),
    ),
)
def test_writers_default_to_workspace_write_and_reviewers_to_read_only(
    lane: Lane, name: str, args: tuple[str, ...], launcher_default: list[str]
) -> None:
    result = lane.run(*args, name=name)
    assert result.returncode == 0, result.stderr
    caller = list(args)
    launcher_argv = lane.argv()[: len(lane.argv()) - len(caller)]
    assert lane.argv()[len(launcher_argv) :] == caller
    assert [launcher_argv[i + 1] for i, a in enumerate(launcher_argv) if a == "-s"] == (
        launcher_default
    )


def test_codex_runs_in_the_dedicated_lane_home(lane: Lane) -> None:
    orca = lane.home / ".config/orca/codex-accounts/acct/home"
    inherited = {
        "CODEX_HOME": str(orca),
        "ORCA_CODEX_HOME": str(orca),
        "OPENAI_API_KEY": "sk-openai-fixture",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "CODEX_API_KEY": "fixture",
        "CLAUDE_CODE_OAUTH_TOKEN": "fixture",
    }
    result = lane.run("exec", "task", env=inherited)
    assert result.returncode == 0, result.stderr
    env = lane.env()
    home = lane.prefix / "codex-home"
    assert env["CODEX_HOME"] == str(home)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    # Orca's pane-home marker and every stale OpenAI or Claude credential are gone.
    for name in (
        "ORCA_CODEX_HOME",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        "CODEX_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        assert env[name] == "", name
    assert not orca.exists(), "the Orca account home is never created or written"


@pytest.mark.parametrize("login", (".codex", ".config/orca/codex-accounts/acct/home"))
def test_a_lane_home_that_resolves_into_a_login_home_is_refused(lane: Lane, login: str) -> None:
    (lane.home / login).mkdir(parents=True)
    (lane.prefix / "codex-home").symlink_to(lane.home / login)
    result = lane.run("exec", "task")
    assert result.returncode == 3
    assert not (lane.record / "codex.argv").exists(), "Codex never starts"
    assert not (lane.record / "with-keys.calls").exists(), "and no key is fetched"


def test_the_launch_folder_is_trusted_for_that_run_only(lane: Lane, tmp_path: Path) -> None:
    # Orca keeps worktree trust in the homes it selects; this lane home has none of it.
    link = tmp_path / "linked-worktree"
    link.symlink_to(lane.worktree)
    result = lane.run("exec", "task", cwd=link, env={"PWD": str(link)})
    assert result.returncode == 0, result.stderr
    assert lane.overrides()["projects"] == {
        str(link): {"trust_level": "trusted"},
        str(lane.worktree): {"trust_level": "trusted"},
    }
    assert not (lane.prefix / "codex-home/config.toml").exists(), "nothing persisted"


@pytest.mark.parametrize(
    "probe",
    (
        ("--version",),
        ("--help",),
        # A flag before --version, and Codex's management subcommands (cli/src/main.rs:145-245).
        ("--dangerously-bypass-hook-trust", "--version"),
        ("login", "status"),
        ("features", "list", "-c", "check_for_update_on_startup=false"),
        ("completion", "bash"),
    ),
)
def test_offline_probes_run_without_the_key_or_a_receipt(lane: Lane, probe: tuple) -> None:
    result = lane.run(*probe)
    assert result.returncode == 0, result.stderr
    assert lane.argv() == list(probe)
    assert lane.env()["CODEX_HOME"] == str(lane.prefix / "codex-home")
    assert not (lane.record / "with-keys.calls").exists()
    assert not (lane.record / "receipt.argv").exists()


def test_every_installed_name_is_one_the_launcher_serves(lane: Lane) -> None:
    assert sorted(lane.installed) == ["bin/sextant-codex", "bin/sextant-codex-review"]
    for link in lane.installed.values():
        assert lane.run("exec", "task", via=link).returncode == 0
    unknown = lane.home / ".local/bin/sextant-codex-x"
    unknown.symlink_to(lane.prefix / "codex-launch.sh")
    assert lane.run("exec", "task", name="sextant-codex-x").returncode == 2


def test_ao_never_resolves_codex_to_the_lane_launcher(lane: Lane, tmp_path: Path) -> None:
    # #258: AO 0.14.10 reconciles and verifies its Codex accounts by running the `codex` its daemon
    # resolves (codex_account_service.go:98-130, codex_accounts.go:613-630), so that Codex must stay
    # AO's own. ao.sh daemon keeps AO's PATH as given ...
    fake = tmp_path / "bin/ao"
    _script(
        fake,
        '#!/usr/bin/env bash\n[[ "$1" == version ]] && { echo "0.14.10 commit 033d597032e4 x"; '
        'exit 0; }\nprintf "%s" "$PATH" > "$FAKE_LOG"\n',
    )
    given = f"{fake.parent}:/usr/bin:/bin"
    env = {"HOME": str(lane.home), "PATH": given, "FAKE_LOG": str(tmp_path / "daemon-path")}
    run = subprocess.run(
        ["bash", str(ROOT / "deploy/wsl/ao.sh"), "daemon"], env=env, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    assert (tmp_path / "daemon-path").read_text() == given
    # ... install.sh gives the launcher no `codex` name, and the launcher refuses that name before
    # Codex starts or a key is read, so no shim can stand in for AO's Codex.
    assert not [name for name in lane.installed if name.rsplit("/", 1)[-1] == "codex"]
    shim = tmp_path / "shim/codex"
    shim.parent.mkdir()
    shim.symlink_to(lane.prefix / "codex-launch.sh")
    for args in (("app-server",), ("login", "status"), ("exec", "task")):
        assert lane.run(*args, via=shim).returncode == 2
    assert not (lane.record / "codex.argv").exists()
    assert not (lane.record / "with-keys.calls").exists()


def test_codex_keeps_the_signal_dispositions_a_direct_launch_has(lane: Lane) -> None:
    # Bash makes a background child ignore INT and QUIT; Codex runs as one so the receipt can
    # follow it, and must still stop on the terminal's Ctrl-C as a directly launched Codex does.
    codex = lane.home / ".local/share/sextant-agents/node_modules/.bin/codex"
    direct = subprocess.run([str(codex)], env={"PATH": "/usr/bin:/bin"}, check=False)
    assert direct.returncode == 0
    expected = lane.env()["ignored_signals"]
    assert lane.run("exec", "task").returncode == 0
    assert lane.env()["ignored_signals"] == expected


def test_the_receipt_follows_every_run_and_codex_keeps_its_exit_status(lane: Lane) -> None:
    result = lane.run("exec", "task", env={"FAKE_CODEX_EXIT": "7"})
    assert result.returncode == 7
    run, flag, target = json.loads((lane.record / "receipt.argv").read_text())
    assert flag == "--write"
    assert Path(target) == lane.prefix / "codex-receipts" / f"{run}.json"
    assert json.loads(Path(target).read_text())["run"] == run


# The receipt itself, against OmniRoute's call-log rows and request records at its pin.
def _row(log_id: str, session: str | None, **fields: object) -> dict:
    """A list row as src/lib/usage/callLogs.ts mapSummaryRow returns it."""
    return {
        "id": log_id,
        "timestamp": "2026-11-08T05:33:35.913Z",
        "method": "POST",
        "path": "/v1/responses",
        "status": 200,
        "model": "gpt-6.1-sol",
        "requestedModel": "sextant-gpt",
        "provider": "codex",
        "account": EMAIL,
        "connectionId": "2bc3551a-7e1f-4f8e-9d55-0c1d2e3f4a5b",
        "apiKeyName": "sextant-codex-20261108T060000Z",
        "comboName": "sextant-gpt",
        "detailState": "ready",
        "hasRequestBody": True,
        "clientSessionId": session,
        **fields,
    }


def _record(row: dict, body: object, state: str = "ready") -> dict:
    """The detail as getCallLogById returns it: the row plus its stored request."""
    pipeline = {"clientRawRequest": {"headers": {"authorization": f"Bearer {BEARER}"}}}
    return {**row, "detailState": state, "requestBody": body, "pipelinePayloads": pipeline}


def _max_body() -> dict:
    return {
        "model": "codex/gpt-6.1-sol",
        "reasoning": {"effort": "max"},
        "input": [{"role": "user", "content": [{"type": "input_text", "text": PROMPT}]}],
    }


class Router:
    """OmniRoute's `api usage` list and detail commands, held in memory."""

    def __init__(self, rows: list[dict], records: dict[str, list[dict]]) -> None:
        self.rows, self.records, self.calls = rows, records, []

    def __call__(self, *args: str) -> object:
        self.calls.append(args)
        if args[:2] == ("usage", "get-api-usage-call-logs"):
            return self.rows
        if args[:3] == ("usage", "get-api-usage-call-logs-id-", "--id"):
            pending = self.records[args[3]]
            return pending.pop(0) if len(pending) > 1 else pending[0]
        raise AssertionError(args)


@pytest.fixture
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(receipt.time, "sleep", lambda seconds: None)


def test_the_receipt_attests_effort_from_the_request_record_and_keeps_only_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], no_wait
) -> None:
    rows = [
        _row("c1", RUN),
        _row("c2", RUN, connectionId="7f00aa11-0000-4000-8000-000000000000"),
        _row("c3", "another-run", model="gpt-6.1-terra"),
        _row("c4", None),
    ]
    omitted = "[omitted: call log artifact size limit exceeded]"
    router = Router(
        rows, {"c1": [_record(rows[0], _max_body())], "c2": [_record(rows[1], omitted)]}
    )
    monkeypatch.setattr(receipt.ok, "_cli", router)
    target = tmp_path / "receipts" / f"{RUN}.json"
    assert receipt.main([RUN, "--write", str(target)]) == 0
    written = json.loads(target.read_text())
    assert written["run"] == RUN
    assert written["calls"] == 2
    assert written["paths"] == {"POST /v1/responses": 2}
    assert written["status"] == {"200": 2}
    assert written["served_models"] == {"gpt-6.1-sol": 2}
    assert written["connections"] == {"2bc3551a": 1, "7f00aa11": 1}
    # The effort comes from each request record; a record the size cap emptied is counted apart,
    # neither as max nor against it.
    assert written["reasoning_effort"] == {"max": 1, "not retained": 1}
    assert written["pin_ok"] is True
    # Another run's records are never read.
    read = [call[3] for call in router.calls if call[1] == "get-api-usage-call-logs-id-"]
    assert sorted(read) == ["c1", "c2"]
    shown = target.read_text() + "".join(capsys.readouterr())
    for withheld in (PROMPT, BEARER, EMAIL, "codex/gpt-6.1-sol"):
        assert withheld not in shown, withheld


def _body(effort: str) -> dict:
    return {**_max_body(), "reasoning": {"effort": effort}}


OMITTED = "[omitted: call log artifact size limit exceeded]"


@pytest.mark.parametrize(
    ("calls", "pin_ok"),
    (
        ((("gpt-6.1-sol", _max_body()), ("gpt-6.1-sol", _max_body())), True),
        # Any call at another effort, or served by another model, breaks the pin.
        ((("gpt-6.1-sol", _max_body()), ("gpt-6.1-sol", _body("high"))), False),
        ((("gpt-6.1-sol", _max_body()), ("gpt-6.1-terra", _max_body())), False),
        # Records that kept no body are no evidence either way, so they alone attest nothing.
        ((("gpt-6.1-sol", OMITTED), ("gpt-6.1-sol", None)), False),
    ),
)
def test_a_run_attests_its_pin_only_when_its_calls_show_max_on_the_pinned_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_wait, calls: tuple, pin_ok: bool
) -> None:
    rows = [_row(f"c{n}", RUN, model=model) for n, (model, _) in enumerate(calls)]
    records = {row["id"]: [_record(row, body)] for row, (_, body) in zip(rows, calls, strict=True)}
    # A record still being written is read again before it counts.
    records["c0"].insert(0, _record(rows[0], None, state="pending"))
    monkeypatch.setattr(receipt.ok, "_cli", Router(rows, records))
    target = tmp_path / "receipt.json"
    assert receipt.main([RUN, "--write", str(target)]) == 0
    written = json.loads(target.read_text())
    assert written["calls"] == len(calls)
    assert written["pin_ok"] is pin_ok


def test_a_run_with_no_attributed_call_or_no_router_attests_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], no_wait
) -> None:
    monkeypatch.setattr(receipt.ok, "_cli", Router([_row("c3", "another-run")], {}))
    target = tmp_path / "receipt.json"
    assert receipt.main([RUN, "--write", str(target)]) == 0
    written = json.loads(target.read_text())
    assert written["calls"] == 0 and written["pin_ok"] is False

    def unreachable(*args: str) -> object:
        raise receipt.ok.KeyError_("omniroute api usage get-api-usage-call-logs failed (exit 1)")

    monkeypatch.setattr(receipt.ok, "_cli", unreachable)
    missing = tmp_path / "missing.json"
    assert receipt.main([RUN, "--write", str(missing)]) == 1
    assert not missing.exists()
    assert "Traceback" not in capsys.readouterr().err
