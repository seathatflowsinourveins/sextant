"""Build the sealed 2026-11-09 ranking-e2e cohort JSON.

The e2e-omh replay published the candidate table (``metrics.json``) and the
prior-session daily bars.  This module turns them into the cohort file the
harness loads, deriving a candidate's prior close from the official prior-day
daily close (the replay's own convention).  It never invents a cohort: the
truth and control sets are the frozen K3 predicates, and the declared counts in
``metrics.json`` are cross-checked before a file is written.

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
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

SCHEMA = "ranking-e2e.cohort/1"
MIN_MOVE = Decimal("0.05")
MIN_PREMARKET_DOLLAR_VOLUME = Decimal("1000000")
PRIOR_CLOSE_QUANTUM = Decimal("0.0001")


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
    missing prior-day close falls back to ``last_close / (1 + move)``; the
    fallback is recorded by its arithmetic, never invented.
    """
    priors = tuple(sorted(prior_sessions))
    if not priors or priors[-1] >= session:
        raise ValueError("prior sessions must be complete and before the session")
    candidates: list[dict[str, Any]] = []
    truth: list[str] = []
    controls: list[str] = []
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
        prior_close = daily_closes.get(symbol)
        if prior_close is None or prior_close <= 0:
            growth = Decimal(1) + move
            if growth <= 0:
                raise ValueError(f"{symbol}: cannot derive a prior close from move {move}")
            prior_close = (last_close / growth).quantize(
                PRIOR_CLOSE_QUANTUM, rounding=ROUND_HALF_UP
            )
        candidates.append(
            {
                "symbol": symbol,
                "move": str(move),
                "premarket_dollar_volume": str(premarket),
                "full_dollar_volume": str(full),
                "prior_close": str(prior_close),
            }
        )
        if premarket >= MIN_PREMARKET_DOLLAR_VOLUME:
            if move >= MIN_MOVE:
                truth.append(symbol)
            else:
                controls.append(symbol)

    declared = metrics.get("primary")
    if isinstance(declared, Mapping) and "cohort" in declared:
        if int(declared["cohort"]) != len(truth):
            raise ValueError(
                "primary cohort mismatch: "
                f"metrics says {declared['cohort']}, predicates find {len(truth)}"
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
        "candidates": candidates,
        "truth": truth,
        "controls": controls,
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
