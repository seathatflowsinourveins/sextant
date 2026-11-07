"""Stage C1's arm x case reservations in the #102 inbox (write-only, no ledger)."""
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path.home() / "sextant-data/c1-scenario/lib"))
from handoff import write_batch  # noqa: E402

from sextant.exits.policy import ExitParams  # noqa: E402
from sextant.validation.trials import snapshot_hash  # noqa: E402

PROTOCOL = "904747d4b928cae4af890597ef2c403f8c90fb86dfbe189a1b36a09c104e2110"
ROOT = Path.home() / "sextant-data/c1-scenario"
ATTEMPT = Path.home() / "sextant-data/scenario-130/c1"
RESERVE = ATTEMPT / "reserve"
ARMS = ROOT / "run/arms"

SHA_68 = "61174b829bd42da60ab719bae9c43bead807f0e5"
SHA_214 = "98f10433dbfcd8ef7e0ac9c37462b79a3b6cb161"
SHA_PR2 = "09e579fa27b4af5ae458e5b6e899196fd681d430"
SHA_111 = "2bb696275ef2a057b2203abeb40f09b3b70de391"
SHA_INT = "fc50653ee62006385f6f92765f4151a38b64af40"

CASES = {
    "A": {
        "symbol": "PARA", "cusip": "06682J803",
        "entry_session": "2026-11-03", "sessions": ["2026-11-03", "2026-11-04"],
        "marks": {"open": "3.73", "prior_close": "1.69", "high": "8.93",
                   "high_pct": "4.28", "volume": "101700000", "next_close": "0.319",
                   "next_pct": "-0.88"},
    },
    "B": {
        "symbol": "PARA", "cusip": "06682J803",
        "entry_session": "2026-10-27", "sessions": ["2026-10-27"],
        "marks": {"split": "1:10 reverse", "intraday_pct_adjusted": "0.57"},
    },
    "C": {
        "symbol": "SPCX", "cusip": None,
        "entry_session": "2026-10-21", "sessions": ["2026-10-20", "2026-10-21", "2026-10-22"],
        "marks": {"event": "Q3 8-K after 2026-10-20 close", "open": "160.56",
                   "gap_pct": "0.086", "high": "166.18", "high_pct": "0.124",
                   "next_pct": "-0.091"},
    },
}

ENTRY_NULLS = json.loads(
    (Path.cwd() / "lanes/sim/entry-parameters.json").read_text()
)
entry_params = {row["name"]: None for row in ENTRY_NULLS}

exit_params = {k: str(v) for k, v in ExitParams.starts().__dict__.items() if v is not None}

block = "scenario-130:" + snapshot_hash(
    {"protocol_sha256": PROTOCOL, "cases": {k: v["sessions"] for k, v in CASES.items()}}
)

BASES = {
    "detection": dict(
        strategy="stocks-in-play", sha=SHA_INT,
        factor_mask=["opening_window", "rvol", "adv", "atr", "price"],
        params={"detector": "stocks-in-play", "opening_window": 5, "lookback": 14,
                 "open_above": "5", "adv_at_least": "1000000", "atr_above": "0.5",
                 "rvol_at_least": "1", "top_n": 20,
                 "denominator": "mean_prior_opening_windows",
                 "parameter_state": "PUBLISHED", "top20_external": "NOT_RUN"},
        parameter_state="PUBLISHED",
    ),
    "entry": dict(
        strategy="entry-first-leg-reclaim", sha=SHA_68,
        factor_mask=["first-leg", "reclaim", "sizing", "expiry"],
        params={**entry_params, "parameter_state": "UNAVAILABLE",
                 "source": "lanes/sim/entry-parameters.json"},
        parameter_state="UNAVAILABLE",
    ),
    "exit": dict(
        strategy="exit-engine-p2", sha=SHA_PR2,
        factor_mask=["x2-trigger", "x3-arming", "x4-breach", "x5-bid-sell"],
        params={**exit_params, "x5_label": "PENDING",
                 "source": "src/sextant/exits/policy.py:106"},
        parameter_state="RECORDED_START",
    ),
    "control-hold-flat": dict(
        strategy="hold-flat", sha=SHA_INT, factor_mask=["control"],
        params={"cost_bps_per_side": ["3", "6"], "position": "none"},
        parameter_state="DEFINED",
    ),
    "control-hold-1555": dict(
        strategy="hold-to-1555", sha=SHA_INT, factor_mask=["control"],
        params={"cost_bps_per_side": ["3", "6"], "flat": "15:55 ET open"},
        parameter_state="DEFINED",
    ),
    "harness-stack": dict(
        strategy="sandbox-full-stack", sha=SHA_111,
        factor_mask=["ranking", "generation_freshness", "entry", "sizing", "exit",
                      "custody", "pacer", "guard", "reentry_admission"],
        params={"profile": "lanes/sim/sandbox-replay-fixture.json",
                 "profile_scope": "FIXTURE_ONLY"},
        parameter_state="FIXTURE_ONLY",
    ),
}

rows = []
for case, spec in CASES.items():
    for arm, base in BASES.items():
        arm_id = f"scenario-130:c1:{arm}:{case.lower()}"
        sandbox = dict(
            case=case, symbol=spec["symbol"], cusip=spec["cusip"],
            entry_session=spec["entry_session"], sessions=spec["sessions"],
            marks=spec["marks"], protocol_sha256=PROTOCOL,
            purpose="MEASUREMENT_ONLY",
            witness_entry="first SIP trade print at/after 09:30:00 ET on entry_session",
            labels={"n": 3, "cohort": "hindsight_selected", "tier": "MODELED",
                     "merit": False, "survivor_only": True,
                     "entry": "NOT_RUN (entry_parameters_unavailable)",
                     "x5": "PENDING", "ranking_66": "NOT_RUN"},
            costs_bps_per_side=["3", "6"] if arm in ("exit", "control-hold-flat",
                                                      "control-hold-1555") else None,
        )
        config = dict(
            arm_id=arm_id,
            arm_run_id=str(ARMS / f"case-{case.lower()}" / arm),
            implementation_sha=base["sha"],
            factor_mask=base["factor_mask"],
            sandbox_config=sandbox,
            sandbox_config_hash=snapshot_hash(sandbox),
            evidence_weights={},
            evidence_weights_hash=snapshot_hash({}),
            params_hash=snapshot_hash(base["params"]),
            tier="MODELED",
            block_set_id=block,
            funding_divergent_session_count=None,
            funding_unverified_session_count=None,
            condition_returns={},
            parameter_state=base["parameter_state"],
            purpose="MEASUREMENT_ONLY",
            protocol_sha256=PROTOCOL,
        )
        rows.append(dict(strategy=base["strategy"], params=base["params"], seed=7,
                         config=config))

receipts = write_batch(RESERVE, "reserve", rows, lane="scenario", issue=130)
manifest = json.loads((RESERVE / "manifest.json").read_text())
print(json.dumps({"dir": str(RESERVE), "count": manifest["count"],
                  **receipts}, indent=2, sort_keys=True))
