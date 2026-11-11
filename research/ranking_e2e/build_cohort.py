"""Build the sealed 2026-11-09 ranking-e2e cohort JSON.

The e2e-omh replay published the candidate table (``metrics.json``) and the
prior-session daily bars.  This module turns them into the cohort file the
harness loads.  A candidate's reference is always the official prior-day daily
close recorded with its source; when that close is missing the candidate keeps
``prior_close: null`` and is excluded with a counted reason.  K2 section 2
forbids a fallback close (an unknown reference stays unknown), so no value is
ever derived from the session's own later price.  The truth and control sets
are the frozen K3 predicates, and the declared counts in ``metrics.json`` are
cross-checked before a file is written.

Usage::

    uv run --frozen python -m research.ranking_e2e.build_cohort \
        --metrics /path/to/metrics.json \
        --daily-dir /path/to/raw/1day/2026-11-06 \
        --out /path/to/cohort-2026-11-09.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = "ranking-e2e.cohort/1"
MIN_MOVE = Decimal("0.05")
MIN_PREMARKET_DOLLAR_VOLUME = Decimal("1000000")
OFFICIAL_PRIOR_CLOSE = "official_prior_daily_close"
MISSING_PRIOR_CLOSE = "missing_official_prior_close"
LABELS = {
    "survivor_only": True,
    "pit_verified": False,
    "inference_eligible": False,
    "universe": "e2e-omh 2026-11-09 bar-close candidate table; no dated PIT membership",
}


def _decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)


def load_daily_closes(root: Path) -> dict[str, Decimal]:
    """Read one daily bar per symbol from an e2e-omh ``raw/1day`` day directory."""
    closes: dict[str, Decimal] = {}
    for path in sorted(Path(root).glob("*.json")):
        data = _load_json(path)
        for page in data["pages"]:
            parsed = json.loads(page, parse_float=Decimal) if isinstance(page, str) else page
            for symbol, rows in parsed["bars"].items():
                if rows:
                    close = _decimal(rows[-1]["c"])
                    if close > 0:
                        closes[symbol] = close
    return closes


def build_cohort(
    metrics: Mapping[str, Any],
    daily_closes: Mapping[str, Decimal],
    *,
    session: date,
    prior_sessions: Sequence[date],
) -> dict[str, Any]:
    """Return a cohort document with the frozen truth/control predicates applied.

    Truth is ``move >= 5% and premarket dollar volume >= $1m``; controls are the
    remaining candidates with ``move < 5%`` and the same premarket floor.  A
    missing official prior-day close is never derived from ``last_close`` or
    ``move``: the candidate records ``prior_close: null`` and a counted
    exclusion, and is kept out of both the truth and control sets (K2 section 2
    and 3).  Every candidate carries the source of its prior close.
    """
    priors = tuple(sorted(prior_sessions))
    if not priors or priors[-1] >= session:
        raise ValueError("prior sessions must be complete and before the session")
    candidates: list[dict[str, Any]] = []
    truth: list[str] = []
    controls: list[str] = []
    excluded: list[dict[str, str]] = []
    planned_truth = 0
    seen: set[str] = set()
    for row in metrics["candidates"]:
        symbol = row["symbol"]
        if not symbol or symbol in seen:
            raise ValueError(f"duplicate or empty symbol: {symbol!r}")
        seen.add(symbol)
        move = _decimal(row["move"])
        last_close = _decimal(row["last_close"])
        premarket = _decimal(row["premarket_dollar_volume"])
        full = _decimal(row["full_dollar_volume"])
        wants_truth = premarket >= MIN_PREMARKET_DOLLAR_VOLUME and move >= MIN_MOVE
        wants_control = premarket >= MIN_PREMARKET_DOLLAR_VOLUME and move < MIN_MOVE
        if wants_truth:
            planned_truth += 1
        prior_close = daily_closes.get(symbol)
        if prior_close is None or prior_close <= 0:
            candidates.append(
                {
                    "symbol": symbol,
                    "move": str(move),
                    "premarket_dollar_volume": str(premarket),
                    "full_dollar_volume": str(full),
                    "last_close": str(last_close),
                    "prior_close": None,
                    "prior_close_source": MISSING_PRIOR_CLOSE,
                }
            )
            excluded.append({"symbol": symbol, "reason": MISSING_PRIOR_CLOSE})
            continue
        candidates.append(
            {
                "symbol": symbol,
                "move": str(move),
                "premarket_dollar_volume": str(premarket),
                "full_dollar_volume": str(full),
                "last_close": str(last_close),
                "prior_close": str(prior_close),
                "prior_close_source": OFFICIAL_PRIOR_CLOSE,
            }
        )
        if wants_truth:
            truth.append(symbol)
        elif wants_control:
            controls.append(symbol)

    declared = metrics.get("primary")
    if isinstance(declared, Mapping) and "cohort" in declared:
        if int(declared["cohort"]) != planned_truth:
            raise ValueError(
                "primary cohort mismatch: "
                f"metrics says {declared['cohort']}, predicates find {planned_truth}"
            )
    secondary = metrics.get("secondary")
    if isinstance(secondary, Mapping) and "cohort" in secondary:
        wider = sum(
            1
            for row in metrics["candidates"]
            if _decimal(row["move"]) >= MIN_MOVE
            and _decimal(row["full_dollar_volume"]) >= MIN_PREMARKET_DOLLAR_VOLUME
        )
        if int(secondary["cohort"]) != wider:
            raise ValueError(
                "secondary cohort mismatch: "
                f"metrics says {secondary['cohort']}, predicates find {wider}"
            )
    return {
        "schema": SCHEMA,
        "session": session.isoformat(),
        "prior_sessions": [day.isoformat() for day in priors],
        "labels": dict(LABELS),
        "candidates": candidates,
        "truth": truth,
        "controls": controls,
        "excluded": excluded,
        "counts": {
            "candidates": len(candidates),
            "planned_truth": planned_truth,
            "observed_truth": len(truth),
            "excluded": len(excluded),
        },
    }


def _parse_sessions(value: str) -> tuple[date, ...]:
    return tuple(date.fromisoformat(part.strip()) for part in value.split(",") if part.strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--daily-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--session", type=date.fromisoformat, default=date(2026, 11, 9))
    parser.add_argument(
        "--prior-sessions",
        type=_parse_sessions,
        default=_parse_sessions("2026-11-02,2026-11-03,2026-11-04,2026-11-05,2026-11-06"),
    )
    args = parser.parse_args(argv)
    metrics = _load_json(args.metrics)
    cohort = build_cohort(
        metrics,
        load_daily_closes(args.daily_dir),
        session=args.session,
        prior_sessions=args.prior_sessions,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(cohort, indent=2) + "\n", encoding="utf-8")
    print(
        f"{args.out}: {len(cohort['candidates'])} candidates, "
        f"{len(cohort['truth'])} truth, {len(cohort['controls'])} controls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
