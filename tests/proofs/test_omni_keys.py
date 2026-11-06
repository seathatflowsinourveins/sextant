"""OmniRoute runtime keys: minted by the router's CLI, sealed, restricted, renewed, revoked."""

import importlib.util
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("omni_keys", ROOT / "scripts" / "omni_keys.py")
assert SPEC and SPEC.loader
ok = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ok)
HANDOFF = ok.hermes_handoff
NOW = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)
PLANTED = "sk-router-value-that-must-never-surface"


class Router:
    """OmniRoute's /api/keys and /api/combos contract at 3.8.53, held in memory."""

    def __init__(self, combo_model: str = "codex/gpt-6.1-sol-max") -> None:
        self.keys: list[dict] = []
        self.calls: list[tuple[str, ...]] = []
        self.combo = [{"kind": "model", "model": combo_model}]
        self.minted = 0
        self.log: list[str] = []

    def __call__(self, *args: str) -> object:
        self.calls.append(args)
        if args[:2] == ("api-keys", "get-api-keys"):
            return {"keys": [dict(k) for k in self.keys]}
        if args[:2] == ("combos", "get-api-combos"):
            return {"combos": [{"name": "sextant-gpt", "models": self.combo}]}
        if args[:2] == ("api-keys", "post-api-keys"):
            body = json.loads(args[3])
            self.minted += 1
            key = {"id": f"id-{self.minted}", **body}
            self.keys.append(key)
            return {**key, "key": PLANTED}
        if args[:2] == ("api-keys", "delete-api-keys-id-"):
            self.log.append(f"revoke {args[3]}")
            self.keys = [k for k in self.keys if k["id"] != args[3]]
            return {"ok": True}
        raise AssertionError(args)


@pytest.fixture
def router(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Router:
    fake = Router()
    monkeypatch.setattr(ok, "_cli", fake)
    sealed = tmp_path / "sealed"
    store = tmp_path / "keys.sh"
    store.write_text(f'#!/usr/bin/env bash\n[[ "$3" == --sealed-stdin ]] && cat > "{sealed}/$2"\n')
    sealed.mkdir()
    monkeypatch.setattr(ok, "KEYS", store)
    monkeypatch.setattr(ok, "stored", lambda name: (sealed / name).exists())
    monkeypatch.setattr(ok, "probe", lambda name: True)
    monkeypatch.setattr(ok, "hermes_handoff", lambda since: fake.log.append("handoff"))

    def models(request: Request, timeout: int) -> nullcontext[SimpleNamespace]:
        assert request.full_url == "http://127.0.0.1:22128/v1/models"
        assert request.get_header("Authorization") == f"Bearer {PLANTED}"
        return nullcontext(SimpleNamespace(status=200))

    monkeypatch.setattr(ok.urllib.request, "urlopen", models)
    fake.sealed = sealed  # type: ignore[attr-defined]
    return fake


def test_mint_seals_a_restricted_thirty_day_key_and_never_shows_it(
    router: Router, capsys: pytest.CaptureFixture[str]
) -> None:
    assert ok.main(["renew", "pi"]) == 0
    sealed = (router.sealed / "OMNIROUTE_KEY_PI").read_text()  # type: ignore[attr-defined]
    assert sealed == f"{PLANTED}\nNS_SEALED_TRANSFER_COMPLETE\n", "stdin frame keys.sh requires"
    out = capsys.readouterr()
    assert PLANTED not in out.out + out.err
    assert all(PLANTED not in arg for call in router.calls for arg in call), "never on argv"
    (key,) = router.keys
    assert key["modelAccessMode"] == "restricted"
    assert key["allowedModels"] == ["sextant-gpt"] == key["allowedCombos"]
    assert not any(ok.CLAUDE.search(m) for m in key["allowedModels"])
    assert key["name"].startswith("sextant-pi-") and "scopes" not in key, "no manage scope"
    assert datetime.fromisoformat(key["expiresAt"]) - datetime.now(UTC) > timedelta(days=29)


def test_renewal_converges_and_revokes_old_ids_only_after_the_new_key_works(
    router: Router,
) -> None:
    assert ok.main(["renew"]) == 0
    assert sorted(ok.RUNTIMES) == sorted(k["name"].split("-")[1] for k in router.keys)
    minted = router.minted
    assert ok.main(["renew"]) == 0 and router.minted == minted, "a current key is left alone"
    assert ok.main(["due"]) == 1
    # Near expiry: one replacement, and the old ID revoked.
    old = next(k for k in router.keys if k["name"].startswith("sextant-hermes-"))
    old["expiresAt"] = (datetime.now(UTC) + timedelta(days=6)).isoformat()
    assert ok.main(["due"]) == 0
    assert ok.main(["renew", "hermes"]) == 0
    hermes = [k for k in router.keys if k["name"].startswith("sextant-hermes-")]
    assert len(hermes) == 1 and hermes[0]["id"] != old["id"]


@pytest.mark.parametrize("failure", [401, TimeoutError(), URLError("router unavailable")])
def test_failed_replacement_probe_preserves_the_old_sealed_value(
    router: Router, monkeypatch: pytest.MonkeyPatch, failure: int | Exception
) -> None:
    old = {
        "id": "old-runtime-id",
        "name": "sextant-pi-previous",
        "expiresAt": (datetime.now(UTC) + timedelta(days=6)).isoformat(),
    }
    router.keys.append(old)
    entry = router.sealed / "OMNIROUTE_KEY_PI"  # type: ignore[attr-defined]
    previous = b"previous-runtime-value\nNS_SEALED_TRANSFER_COMPLETE\n"
    entry.write_bytes(previous)
    monkeypatch.setattr(ok, "probe", lambda name: False)

    def reject(_request: object, timeout: int) -> nullcontext[SimpleNamespace]:
        if isinstance(failure, Exception):
            raise failure
        return nullcontext(SimpleNamespace(status=failure))

    monkeypatch.setattr(ok.urllib.request, "urlopen", reject)
    assert ok.main(["renew", "pi"]) == 1
    assert entry.read_bytes() == previous, "failed replacement must not overwrite the stored key"
    assert router.keys == [old], "keep the old router key and revoke only the rejected replacement"


def test_a_claude_combo_or_a_failed_seal_mints_nothing_that_survives(
    router: Router, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router.combo = [{"kind": "model", "model": "agy/claude-opus-5-5"}]
    assert ok.main(["renew", "pi"]) == 1 and router.minted == 0, "cc stays native"
    router.combo = [{"kind": "model", "model": "codex/gpt-6.1-sol-max"}]
    broken = tmp_path / "broken.sh"
    broken.write_text("#!/usr/bin/env bash\nexit 1\n")
    monkeypatch.setattr(ok, "KEYS", broken)
    assert ok.main(["renew", "pi"]) == 1
    assert router.minted == 1 and router.keys == [], "the unsealed key is revoked by its ID"


def test_names_are_registered_and_renewal_is_a_lifecycle_step() -> None:
    known = (ROOT / "scripts" / "keys.sh").read_text().split("KNOWN=(", 1)[1].split(")", 1)[0]
    assert all(name in known for name in ok.RUNTIMES.values())
    assert ok.LIFETIME == timedelta(days=30) and ok.RENEW_WITHIN == timedelta(days=7)
    precheck = (ROOT / "deploy" / "wsl" / "lifecycle-precheck.sh").read_text()
    assert "python3 -I scripts/omni_keys.py due" in precheck
    prompt = (ROOT / "deploy" / "wsl" / "lifecycle-prompt.md").read_text()
    assert "just omni-keys renew" in prompt
    assert "\nomni-keys *args:\n" in (ROOT / "justfile").read_text()


def test_hermes_revokes_only_after_clients_relaunch_and_the_gateway_restarts(
    router: Router, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher = tmp_path / "api-launch.sh"
    launcher.write_text("-k OMNIROUTE_KEY_HERMES:OMNIROUTE_API_KEY")
    (tmp_path / "hermes").symlink_to(launcher)
    monkeypatch.setattr(ok, "LAUNCHER", launcher)
    monkeypatch.setattr(ok, "HERMES_CLI", tmp_path / "hermes")
    monkeypatch.setattr(ok, "hermes_handoff", HANDOFF)
    monkeypatch.setattr(ok.time, "sleep", lambda seconds: None)
    old_start = NOW - timedelta(days=1)
    gateway = {"now": (100, old_start)}
    monkeypatch.setattr(ok, "hermes_gateway", lambda: gateway["now"])
    monkeypatch.setattr(ok, "hermes_clients", lambda before: [("term_old", "wt-1")])
    restart = {"rc": 1}

    def run(*command: str) -> int:
        router.log.append(" ".join(command[1:4]))
        if command[1:3] == ("gateway", "restart"):
            if restart["rc"] == 0:
                gateway["now"] = (200, datetime.now(UTC) + timedelta(seconds=5))
            return restart["rc"]
        return 0

    monkeypatch.setattr(ok, "_run", run)
    router.keys.append(
        {
            "id": "old",
            "name": "sextant-hermes-20261001T000000Z",
            "expiresAt": "2026-11-08T00:00:00Z",
        }
    )
    assert ok.main(["renew", "hermes"]) == 1, "a busy gateway refuses the restart"
    assert [k["id"] for k in router.keys] == ["old", "id-1"], "so the old key stays"
    assert not any(e.startswith("revoke") for e in router.log)
    restart["rc"] = 0
    assert ok.main(["renew", "hermes"]) == 0
    assert router.minted == 1, "the next run finishes the sealed key instead of minting again"
    assert [k["id"] for k in router.keys] == ["id-1"]
    order = [e for e in router.log if e.split()[0] in {"agent", "terminal", "gateway", "revoke"}]
    assert order[-4:] == [
        "agent launch --agent",
        "terminal close --terminal",
        "gateway restart --detach",
        "revoke old",
    ]
    launcher.write_text("-k OMNIROUTE_API_KEY")
    router.keys.append(
        {
            "id": "old2",
            "name": "sextant-hermes-20261002T000000Z",
            "expiresAt": "2026-11-08T00:00:00Z",
        }
    )
    assert ok.main(["renew", "hermes"]) == 1, (
        "never a gateway restart on a launcher without the key"
    )
    assert "old2" in [k["id"] for k in router.keys]
