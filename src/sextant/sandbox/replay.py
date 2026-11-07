"""Canonical-reservation-gated full-stack S replay; no live feed/ledger writer.

Native R translation and isolated arms follow pinned S0 sandbox_witness.py.
Every actual invocation consumes one posted RUNNING reservation; failures stay
counted. Source/config/tape identities freeze before the sole writer reserves.
"""

import argparse
import json
import os
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader import __version__
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LoggerConfig
from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
from nautilus_trader.execution import DefaultFillModel, MakerTakerFeeModel, StaticLatencyModel
from nautilus_trader.model import (
    AccountType,
    Bar,
    ClientId,
    ClientOrderId,
    CustomData,
    Money,
    OmsType,
    QuoteTick,
    TraderId,
    TradeTick,
    Venue,
)

from sextant.sandbox.account import AccountStack
from sextant.sandbox.handoff import canonical_reservation, digest, stage_handoff, wire
from sextant.sandbox.market import MarketStack
from sextant.sandbox.node import SandboxBinding, build_plan, build_shell
from sextant.sandbox.profile import (
    enable_entry_witness,
    enable_session_witness,
    load_profile,
    source_identity,
    values,
    verify_implementation,
)
from sextant.sandbox.strategy import FullStackStrategy, StackConfig
from sextant.sandbox.tapes import fixture, recorded

CASES = ("recorded", "aa_a", "aa_b", "kill_owner", "unknown")
SESSION_PIN = "04c85fb829e70a6a4b7957e7c29318fb28558a47"
BINDINGS = tuple(
    SandboxBinding(f"sandbox-stack:{case}", f"S0{tag}", f"S0{tag}-001", f"S0{tag}-001", f"S0{tag}")
    for case, tag in zip(CASES, ("R", "A", "B", "K", "U"), strict=True)
)


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(wire(value) + b"\n")
        output.flush()
        os.fsync(output.fileno())


def _sources(repo: Path, profile: dict, entry_root: Path | None, session_root: Path | None):
    dependency = enable_entry_witness(repo, profile, entry_root)
    dependency.update(enable_session_witness(repo, SESSION_PIN, session_root))
    return source_identity(repo, profile, dependency)


def _tape(case: str, profile: dict, config: dict):
    if case == "recorded":
        return recorded(
            Path(config["inputs"]),
            Path(config["catalog"]),
            Path(config["snapshot"]),
            config["snapshot_sha256"],
        )
    return fixture(profile)


def stage_reservations(
    *,
    repo: Path,
    attempt: Path,
    profile_path: Path,
    entry_root: Path | None,
    session_root: Path | None,
    input_config: dict,
    implementation_sha: str,
):
    verify_implementation(repo, implementation_sha, profile_path)
    profile = load_profile(profile_path)
    sources = _sources(repo, profile, entry_root, session_root)
    _, _, recorded_hashes = _tape("recorded", profile, input_config)
    _, _, fixture_hashes = fixture(profile)
    rows = []
    for binding, case in zip(BINDINGS, CASES, strict=True):
        sandbox = dict(
            case=case,
            binding=asdict(binding),
            stream="DISABLED",
            purpose="MECHANISM_ONLY",
            sources=sources,
            input_config=input_config,
            input_hashes=recorded_hashes if case == "recorded" else fixture_hashes,
            data_client="ALPACA",
            data_client_translation={"SFEED": "ALPACA"},
            execution_client="ALPACA",
            client_translation={binding.client_id: "ALPACA"},
            account_translation={binding.account_id: "ALPACA-001"},
            economic_authority="UNAVAILABLE; fixtures and missing historical execution inputs",
        )
        config = dict(
            arm_id=binding.arm_id,
            arm_run_id=str(attempt / case),
            implementation_sha=implementation_sha,
            factor_mask=[
                "ranking",
                "generation_freshness",
                "entry",
                "sizing",
                "exit",
                "custody",
                "pacer",
                "guard",
                "reentry_admission",
            ],
            sandbox_config=sandbox,
            sandbox_config_hash=digest(sandbox),
            evidence_weights={},
            evidence_weights_hash=digest({}),
            params_hash=digest(profile),
            tier="MODELED",
            block_set_id="sandbox-full-stack-mechanisms/1",
            funding_divergent_session_count=None,
            funding_unverified_session_count=None,
            condition_returns={},
        )
        rows.append(
            dict(
                strategy="sandbox-full-stack",
                params=profile,
                seed=values(profile, "execution")["seed"],
                config=config,
            )
        )
    manifest = stage_handoff(attempt / "reserve", kind="reserve", rows=rows)
    return dict(
        directory=str(attempt / "reserve"),
        rows_sha256=manifest["rows_sha256"],
        manifest_sha256=digest((attempt / "reserve/manifest.json").read_bytes()),
        count=len(rows),
    )


def _memory_available() -> int:
    lines = Path("/proc/meminfo").read_text().splitlines()
    return next(int(line.split()[1]) * 1024 for line in lines if line.startswith("MemAvailable:"))


def _strategy_fleet(shared, instruments, start_ns):
    shared.market = MarketStack(shared)
    return tuple(
        FullStackStrategy(StackConfig(instrument=instrument, shared=shared, start_ns=start_ns))
        for instrument in instruments
    )


def add_native_data(engine, data: list):
    # rc7 register_added_data validates only the first item; batches are homogeneous.
    # Its native market client is venue-named; CustomData routes by DataType.
    for kind in (Bar, QuoteTick, TradeTick, CustomData):
        group = [item for item in data if isinstance(item, kind)]
        if group:
            engine.add_data(group, client_id=ClientId("ALPACA"))


def compare_aa(a: dict, b: dict) -> dict:
    def normalize(result):
        return dict(
            fills=[
                {key: value for key, value in fill.items() if key != "cid"}
                for fill in result["fills"]
            ],
            net=result["net"],
            economic_status=result["economic_status"],
        )

    if not (a.get("mechanism_complete") and b.get("mechanism_complete")) or normalize(
        a
    ) != normalize(b):
        raise ValueError("A/A native mechanism differs or is incomplete")
    return dict(equal=True, normalized=normalize(a), economics="UNAVAILABLE")


def native_execute(request: dict, *, root: Path, instruments: list, data: list) -> dict:
    """Called only after canonical admission and source/tape validation by execute_one."""
    config, profile = request["config"]["sandbox_config"], request["params"]
    case = config["case"]
    binding = SandboxBinding(**config["binding"])
    model = values(profile, "execution")
    start = min(event.ts_init for event in data)
    fee = MakerTakerFeeModel(
        maker_rate=Decimal(model["maker_rate"]), taker_rate=Decimal(model["taker_rate"])
    )
    latency = StaticLatencyModel(
        base_latency_nanos=model["base_latency_ns"],
        insert_latency_nanos=model["insert_latency_ns"],
        update_latency_nanos=model["update_latency_ns"],
        cancel_latency_nanos=model["cancel_latency_ns"],
    )
    fill = DefaultFillModel(
        prob_fill_on_limit=float(model["prob_fill_on_limit"]),
        prob_slippage=float(model["prob_slippage"]),
        random_seed=model["seed"],
    )
    # Actual native S construction with the same class/profile, never connected.
    s_account = AccountStack(
        binding=binding,
        profile=profile,
        root=root / "s-construction",
        instruments=instruments,
        case=case,
        data_client="SFEED",
        execution_client=binding.client_id,
    )
    s_strategies = _strategy_fleet(s_account, instruments, start)
    plan = build_plan(
        bindings=BINDINGS,
        starting_balance=Money.from_str(model["starting_balance"]),
        leverage=Decimal(model["leverage"]),
        fee_model=fee,
        latency_model=latency,
        fill_model=fill,
        authority="FIXTURE_ONLY; no operational calibration",
    )
    shell = build_shell(
        plan,
        arm_id=binding.arm_id,
        strategies=s_strategies,
        strategy_ids=frozenset(str(strategy.strategy_id) for strategy in s_strategies),
    )
    node_receipt = dict(
        environment=shell.environment.name,
        running=shell.is_running,
        strategies=len(s_strategies),
        client=binding.client_id,
        account=binding.account_id,
        connection="DISABLED",
    )
    shell.dispose()

    shared = AccountStack(
        binding=binding,
        profile=profile,
        root=root / "native-replay",
        instruments=instruments,
        case=case,
        data_client=config["data_client"],
        execution_client=config["execution_client"],
    )
    strategies = _strategy_fleet(shared, instruments, start)
    engine = BacktestEngine(
        BacktestEngineConfig(
            trader_id=TraderId(f"{binding.client_id}-001"),
            bypass_logging=True,
            logging=LoggerConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
            run_analysis=False,
        )
    )
    try:
        engine.add_venue(
            Venue("ALPACA"),
            OmsType.HEDGING,
            AccountType.MARGIN,
            [Money.from_str(model["starting_balance"])],
            default_leverage=Decimal(model["leverage"]),
            use_random_ids=True,
            bar_execution=False,
            trade_execution=False,
            reject_stop_orders=True,
            fee_model=fee,
            latency_model=latency,
            fill_model=fill,
        )
        for instrument in instruments:
            engine.add_instrument(instrument)
        for strategy in strategies:
            engine.add_strategy(strategy)
        add_native_data(engine, data)
        engine.run()
        shared.refresh(max(event.ts_init for event in data))
        net = {
            str(instrument.id): str(engine.portfolio.net_position(instrument.id))
            for instrument in instruments
        }
        orders = list(engine.cache.orders())
        account = engine.portfolio.account(Venue("ALPACA"))
        owner = (
            None if shared.owner_id is None else engine.cache.order(ClientOrderId(shared.owner_id))
        )
        result = dict(
            arm=request["config"]["arm_id"],
            cohort="recorded-selected-54" if case == "recorded" else "synthetic-mechanism",
            inputs=config["input_hashes"],
            kind="mechanism",
            n=len(shared.fills),
            selected=False,
            study="ADR-0002 full-stack S composition; no trading-merit estimand",
            tier="MODELED",
            version=request["config"]["implementation_sha"],
            case=case,
            s_node_construction=node_receipt,
            native_version=__version__,
            source_identity=config["sources"],
            params_hash=request["config"]["params_hash"],
            input_events=len(data),
            input_bars=sum(isinstance(event, Bar) for event in data),
            instruments=len(instruments),
            component_counts=dict(shared.counts),
            errors=shared.errors,
            fills=shared.fills,
            routes=shared.routes,
            minimum_net=str(shared.minimum_net),
            net=net,
            native_orders=len(orders),
            native_account_id=None if account is None else str(account.id),
            order_namespace=binding.order_namespace,
            all_orders_namespaced=all(
                str(order.client_order_id).startswith(binding.order_namespace + ".")
                or str(order.client_order_id) == shared.owner_id
                for order in orders
            ),
            native_order_types=sorted({order.order_type.name for order in orders}),
            account_translation=config["account_translation"],
            client_translation=config["client_translation"],
            guard_state=shared.guard.state.value,
            guard_loaded=shared.guard.loaded,
            entry_allowed=shared.guard.entry_allowed(),
            flat_receipt=shared.custody.flat_receipt() is not None,
            simulated_command_counts=shared.pacer.to_state("2026-10-27"),
            owner_status=None if owner is None else owner.status.name,
            owner_untouched=shared.owner_id is None
            or all(
                not (route["cid"] == shared.owner_id and route["action"] in {"CANCEL", "MODIFY"})
                for route in shared.routes
            ),
            exit_events=[event for strategy in strategies for event in strategy.events],
            pnl=None,
            daily_net_returns=None,
            economic_status="UNAVAILABLE",
            stream="DISABLED",
            live_s_isolation="NOT_RUN",
            broker_execution="NOT_RUN",
            mechanism_complete=False,
        )
        _write(root / "native-observation.json", result)
        _assert_result(result)
        result["mechanism_complete"] = True
        return result
    finally:
        engine.dispose()
        shared.writer.close()


def _assert_result(result: dict):
    counts = result["component_counts"]
    if result["errors"] or Decimal(result["minimum_net"]) < 0:
        raise ValueError(f"native callback/no-flip failure: {result['errors']}")
    if (
        result["native_account_id"] not in result["account_translation"].values()
        or not result["all_orders_namespaced"]
    ):
        raise ValueError("native account/order namespace differs from its frozen translation")
    if any(
        route["client"] not in result["client_translation"].values() for route in result["routes"]
    ):
        raise ValueError("native command lost its explicit translated execution route")
    if counts.get("strategy_starts") != result["instruments"] or not counts.get("guard_checks"):
        raise ValueError("native strategy/guard callback coverage incomplete")
    if any(Decimal(net) != 0 for net in result["net"].values()):
        raise ValueError("reserved mechanism did not end at modeled net zero")
    if result["case"] == "recorded":
        if result["input_bars"] != counts.get("entry_bar_callbacks"):
            raise ValueError("recorded native callback coverage incomplete")
        if (
            counts.get("recorded_bbo_facts") != result["instruments"]
            or counts.get("bbo_size_unavailable") != result["instruments"]
        ):
            raise ValueError("recorded scanner facts/missing-size callback coverage incomplete")
        if result["native_orders"] or result["fills"]:
            raise ValueError("missing historical authority supplied an order")
    elif result["case"] == "unknown":
        if result["entry_allowed"] or result["guard_loaded"] or result["native_orders"]:
            raise ValueError("unknown persisted state acquired entry authority")
    else:
        if len(result["fills"]) != 2 or result["native_order_types"] != ["LIMIT"]:
            raise ValueError("native entry/exit mechanism did not complete")
        if not result["component_counts"].get("native_sizing_calls"):
            raise ValueError("owning native sizing was not exercised")
        if not counts.get("reentry_admission_checks"):
            raise ValueError("owning re-entry admission was not exercised")
        if result["case"] == "kill_owner":
            if (
                result["entry_allowed"]
                or not result["owner_untouched"]
                or result["owner_status"] != "ACCEPTED"
            ):
                raise ValueError("owner/kill latch failed")
        elif not any(event["event"] == "breach_sell" for event in result["exit_events"]):
            raise ValueError("persistent-breach exit was not exercised")
        elif not result["flat_receipt"]:
            raise ValueError("native terminal lineage did not supply the flat receipt")
        elif not counts.get("reentry:WAIT:entry_provider_unavailable"):
            raise ValueError("re-entry cooldown did not reach missing-provider refusal")


def execute_one(
    *,
    repo: Path,
    attempt: Path,
    case: str,
    ledger_commit: str,
    entry_root: Path | None,
    session_root: Path | None,
) -> dict:
    rows = [json.loads(line) for line in (attempt / "reserve/rows.jsonl").read_text().splitlines()]
    request = next(row for row in rows if row["config"]["sandbox_config"]["case"] == case)
    # No engine or private-source import before the posted canonical reservation.
    canonical = canonical_reservation(repo, ledger_commit, request)
    root = attempt / case
    root.mkdir(exist_ok=False)
    outcome: dict[str, Any]
    try:
        profile, config = request["params"], request["config"]["sandbox_config"]
        if _sources(repo, profile, entry_root, session_root) != config["sources"]:
            raise ValueError("source/fixture profile changed since reservation")
        if _memory_available() < 20 * 1024**3:
            raise ValueError("MemAvailable below owner-required 20 GiB; arm not started")
        instruments, data, hashes = _tape(case, profile, config["input_config"])
        if hashes != config["input_hashes"]:
            raise ValueError("tape identity changed since reservation")
        result = native_execute(request, root=root, instruments=instruments, data=data)
        result["reserved_trial_id"], result["reservation_commit"] = (
            canonical["trial_id"],
            ledger_commit,
        )
        _write(root / "result.json", result)
        outcome = dict(
            arm_run_id=request["config"]["arm_run_id"],
            state="PRUNED",
            error="Mechanism only; historical/executable/economic authority unavailable",
            result=result,
        )
    except Exception as error:
        outcome = dict(
            arm_run_id=request["config"]["arm_run_id"],
            state="FAIL",
            error=f"{type(error).__name__}: {error}",
        )
        observed = root / "native-observation.json"
        if observed.exists():
            outcome["result"] = json.loads(observed.read_text())
    _write(root / "outcome.json", outcome)
    return outcome


def collect_outcomes(attempt: Path):
    rows = [json.loads((attempt / case / "outcome.json").read_text()) for case in CASES]
    by_case = dict(zip(CASES, rows, strict=True))
    pair = [by_case[case] for case in ("aa_a", "aa_b")]
    try:
        comparison = compare_aa(*(row.get("result", {}) for row in pair))
    except (KeyError, ValueError) as error:
        comparison = dict(equal=False, error=str(error), economics="UNAVAILABLE")
        for row in pair:
            row.update(state="FAIL", error=f"A/A comparison: {error}")
    _write(attempt / "aa-comparison.json", comparison)
    manifest = stage_handoff(attempt / "outcome", kind="outcome", rows=rows)
    return dict(
        directory=str(attempt / "outcome"),
        rows_sha256=manifest["rows_sha256"],
        manifest_sha256=digest((attempt / "outcome/manifest.json").read_bytes()),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("reserve", "run", "outcome"))
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument(
        "--profile", type=Path, default=Path("lanes/sim/sandbox-replay-fixture.json")
    )
    parser.add_argument("--entry-source", type=Path)
    parser.add_argument("--session-source", type=Path)
    parser.add_argument("--implementation-sha")
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--ledger-commit")
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--snapshot-sha256")
    args = parser.parse_args()
    repo = Path.cwd()
    if args.operation == "reserve":
        if any(
            getattr(args, name) is None
            for name in ("inputs", "catalog", "snapshot", "snapshot_sha256", "implementation_sha")
        ):
            parser.error("reserve requires input/catalog/snapshot/hash and implementation SHA")
        config = dict(
            inputs=str(args.inputs),
            catalog=str(args.catalog),
            snapshot=str(args.snapshot),
            snapshot_sha256=args.snapshot_sha256,
        )
        result = stage_reservations(
            repo=repo,
            attempt=args.attempt,
            profile_path=args.profile,
            entry_root=args.entry_source,
            session_root=args.session_source,
            input_config=config,
            implementation_sha=args.implementation_sha,
        )
    elif args.operation == "run":
        if args.case is None or args.ledger_commit is None:
            parser.error("run requires case and posted ledger commit")
        result = execute_one(
            repo=repo,
            attempt=args.attempt,
            case=args.case,
            ledger_commit=args.ledger_commit,
            entry_root=args.entry_source,
            session_root=args.session_source,
        )
    else:
        result = collect_outcomes(args.attempt)
    print(wire(result).decode())


if __name__ == "__main__":
    main()
