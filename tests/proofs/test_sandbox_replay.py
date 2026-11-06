"""S run admission/record contracts; no unreserved engine arm in CI."""

import json
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any

import pytest

from sextant.execution.custody import (
    AccountScope,
    AccountSnapshot,
    Custody,
    OrderFact,
    PositionAuthority,
)
from sextant.sandbox.account import AccountStack
from sextant.sandbox.handoff import digest, stage_handoff, validate_reservation
from sextant.sandbox.profile import (
    exit_parameters,
    load_profile,
    ranking_registry,
    reentry_parameters,
)
from sextant.sandbox.tapes import fixture


def reserve_row() -> dict[str, Any]:
    params, sandbox, weights = {"scope": "FIXTURE_ONLY"}, {"stream": "DISABLED"}, {}
    return dict(
        strategy="sandbox-full-stack",
        params=params,
        seed=42,
        config=dict(
            arm_id="fixture-a",
            arm_run_id="fixture-attempt-a",
            implementation_sha="a" * 40,
            factor_mask=["ranking", "entry", "exit", "custody"],
            sandbox_config=sandbox,
            sandbox_config_hash=digest(sandbox),
            evidence_weights=weights,
            evidence_weights_hash=digest(weights),
            params_hash=digest(params),
            tier="MODELED",
            block_set_id="fixture-block",
            funding_divergent_session_count=None,
            funding_unverified_session_count=None,
            condition_returns={},
        ),
    )


def test_staged_handoff_is_lossless_hashed_and_never_overwrites(tmp_path):
    row = reserve_row()
    path = tmp_path / "reserve"
    manifest = stage_handoff(path, kind="reserve", rows=[row])
    raw = (path / "rows.jsonl").read_bytes()
    assert manifest["rows_sha256"] == digest(raw)
    assert json.loads(raw) == row
    assert manifest["tier"] == "MODELED"
    assert manifest["lane"] == "sandbox" and manifest["issue"] == 111
    with pytest.raises(FileExistsError):
        stage_handoff(path, kind="reserve", rows=[row])


@pytest.mark.parametrize("change", ["float", "tier", "hash", "duplicate"])
def test_reservation_handoff_refuses_inconsistent_or_float_identities(tmp_path, change):
    row = reserve_row()
    if change == "float":
        row["config"]["sandbox_config"]["price"] = 10.1
    elif change == "tier":
        row["config"]["tier"] = "BROKER-PAPER"
    elif change == "hash":
        row["config"]["params_hash"] = "0" * 64
    rows = [row, row] if change == "duplicate" else [row]
    with pytest.raises(ValueError):
        stage_handoff(tmp_path / "reserve", kind="reserve", rows=rows)
    assert not (tmp_path / "reserve").exists()


def test_admission_requires_exact_running_canonical_identity():
    row = reserve_row()
    canonical = dict(
        state="RUNNING",
        config=json.dumps(row["config"]),
        params=json.dumps(row["params"]),
        strategy=row["strategy"],
        seed=42,
    )
    assert validate_reservation([canonical], row) == canonical
    for key, value in (("state", "COMPLETE"), ("params", "{}"), ("seed", 99)):
        with pytest.raises(ValueError):
            validate_reservation([canonical | {key: value}], row)
    changed = row | {"config": row["config"] | {"implementation_sha": "b" * 40}}
    with pytest.raises(ValueError):
        validate_reservation([canonical], changed)
    with pytest.raises(ValueError):
        validate_reservation([], row)


def test_failed_outcome_cannot_invent_zero_returns(tmp_path):
    failure = dict(arm_run_id="fixture-attempt-a", state="FAIL", error="source missing")
    stage_handoff(tmp_path / "outcome", kind="outcome", rows=[failure])
    with pytest.raises(ValueError):
        stage_handoff(
            tmp_path / "bad",
            kind="outcome",
            rows=[
                failure
                | {
                    "days": ["2026-10-27"],
                    "daily_net_returns": ["0"],
                }
            ],
        )


def test_native_queued_close_uses_one_book_and_rechecks_smaller_net(tmp_path):
    scope = AccountScope("SIM", "S0A-001")
    book = Custody(scope, tmp_path / "book.json", create=True)
    book.register("S0A.AAA.1", "AAA.ALPACA", "SELL", D(100), source="fixture intent")
    pending = OrderFact("S0A.AAA.1", "AAA.ALPACA", "SELL", D(100), D(0), "INITIALIZED", None)
    book.observe(
        AccountSnapshot(
            scope,
            1,
            {"AAA.ALPACA": D(60)},
            {"AAA.ALPACA": PositionAuthority(D(60), "fixture native house fills")},
            (pending,),
            True,
            1,
            "fixture native and known-unsent intent",
        ),
        now=1,
    )
    account = object.__new__(AccountStack)
    account.custody = book
    assert book.available_exit("AAA.ALPACA") == 0
    assert account.residual("AAA.ALPACA", exclude="S0A.AAA.1") == D(60)


def test_sends_require_an_explicit_matching_native_client_before_other_work():
    account = object.__new__(AccountStack)
    strategy = SimpleNamespace(route="ALPACA")
    with pytest.raises(ValueError, match="explicit"):
        account.submit(strategy, None, client_id=None)


def test_profile_uses_owning_registries_and_fixture_tape_is_reproducible():
    from pathlib import Path

    profile = load_profile(Path(__file__).parents[2] / "lanes/sim/sandbox-replay-fixture.json")
    assert ranking_registry(profile).mover_min_move == D("0.03")
    assert exit_parameters(profile).breach_persist_count == 3
    assert reentry_parameters(profile).cooldown_seconds == D("2")
    instruments, events, hashes = fixture(profile)  # Data construction only; no matching engine.
    assert len(instruments) == 1 and events
    assert hashes == fixture(profile)[2]


def test_scanner_custom_data_keeps_unknown_sizes_and_source_clocks():
    from typing import cast

    from nautilus_trader.model import CustomData

    from sextant.sandbox.tapes import ScannerFacts, scanner_type

    scanner_type()
    data = cast(Any, ScannerFacts)(10, 20, payload='{"bid_size":null}')
    envelope = CustomData(scanner_type(), data)
    assert envelope.ts_event == 10 and envelope.ts_init == 20
    assert json.loads(envelope.data.payload)["bid_size"] is None


def test_replay_adds_homogeneous_native_batches_without_constructing_an_engine():
    from pathlib import Path

    from sextant.sandbox.replay import add_native_data

    profile = load_profile(Path(__file__).parents[2] / "lanes/sim/sandbox-replay-fixture.json")
    _, events, _ = fixture(profile)
    batches = []
    add_native_data(SimpleNamespace(add_data=lambda data, **kw: batches.append((data, kw))), events)
    assert len(batches) == 3
    assert sum(len(batch) for batch, _ in batches) == len(events)
    assert all(len({type(item) for item in batch}) == 1 for batch, _ in batches)


def test_canonical_refusal_precedes_source_loading_and_native_engine(tmp_path, monkeypatch):
    from sextant.sandbox import replay

    path = tmp_path / "reserve"
    row = reserve_row()
    row["config"]["sandbox_config"] = {"case": "recorded"}
    path.mkdir()
    (path / "rows.jsonl").write_text(json.dumps(row) + "\n")

    def refused(*args):
        raise ValueError("canonical refusal")

    def forbidden(*args, **kwargs):
        pytest.fail("unreserved source/native work")

    monkeypatch.setattr(replay, "canonical_reservation", refused)
    monkeypatch.setattr(replay, "_sources", forbidden)
    monkeypatch.setattr(replay, "native_execute", forbidden)
    with pytest.raises(ValueError, match="canonical refusal"):
        replay.execute_one(
            repo=tmp_path,
            attempt=tmp_path,
            case="recorded",
            ledger_commit="a" * 40,
            entry_root=None,
            session_root=None,
        )
    assert not (tmp_path / "recorded").exists()


def test_aa_comparison_ignores_identity_but_never_a_changed_fill():
    from copy import deepcopy

    from sextant.sandbox.replay import compare_aa

    a: dict[str, Any] = dict(
        mechanism_complete=True,
        fills=[dict(cid="S0A.entry", side="BUY", quantity="10", price="10.32", at=1)],
        net={"AAA.ALPACA": "0"},
        economic_status="UNAVAILABLE",
    )
    b = deepcopy(a)
    b["fills"][0]["cid"] = "S0B.entry"
    assert compare_aa(a, b)["equal"]
    b["fills"][0]["price"] = "10.33"
    with pytest.raises(ValueError, match="A/A"):
        compare_aa(a, b)


def test_source_freeze_refuses_uncommitted_code_and_profile(tmp_path):
    import subprocess

    from sextant.sandbox.profile import verify_implementation

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    source = tmp_path / "src/sextant/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("pass\n")
    profile = tmp_path / "fixture.json"
    profile.write_text("{}\n")
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).write_text("# fixture\n")
    git("add", ".")
    git("commit", "-m", "fixture")
    pin = git("rev-parse", "HEAD")
    verify_implementation(tmp_path, pin, profile)
    source.write_text("raise ValueError\n")
    with pytest.raises(ValueError, match="committed"):
        verify_implementation(tmp_path, pin, profile)
    source.write_text("pass\n")
    extra = source.with_name("untracked.py")
    extra.write_text("pass\n")
    with pytest.raises(ValueError, match="committed"):
        verify_implementation(tmp_path, pin, profile)
    extra.unlink()
    profile.write_text('{"changed":true}\n')
    with pytest.raises(ValueError, match="committed"):
        verify_implementation(tmp_path, pin, profile)
