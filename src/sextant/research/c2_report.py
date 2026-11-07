"""C2 report table: reads the outcome batch and prints the per-arm x per-case table.

No numbers are typed by hand: every cell comes from `~/sextant-data/scenario-130/c2/outcome/
rows.jsonl`, which in turn comes from the run JSONs. Decimal only; no floats.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path.home() / "sextant-data" / "c2-scenario"
OUTCOME = Path.home() / "sextant-data" / "scenario-130" / "c2" / "outcome" / "rows.jsonl"
ARMS = (
    "exit-engine-p2",
    "trail-0.5",
    "trail-2.5",
    "trail-0.25",
    "trail-0.1",
    "atr-trail-3",
    "hold-1555",
    "hold-flat",
)
CASES = ("a", "b", "c")
LETTER = {"a": "A", "b": "B", "c": "C"}
SYMBOL = {"a": "PARA", "b": "PARA", "c": "SPCX"}
NY = ZoneInfo("America/New_York")


def pct(value: str | None, digits: str = "0.01") -> str:
    if value is None:
        return "—"
    number = Decimal(value) * 100
    return f"{number.quantize(Decimal(digits)):+.2f}%"


def when(ts: int | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts // 1_000_000_000, NY).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-sha", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--bundle", default="")
    parser.add_argument("--bundle-sha", default="")
    parser.add_argument("--out", default=str(ROOT / "report-body.md"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in OUTCOME.read_text().splitlines() if line.strip()]
    by_key = {}
    for row in rows:
        if row.get("state") != "COMPLETE":
            continue
        result = row["result"]
        by_key[(result["case"], result["arm"])] = result

    lines: list[str] = []
    lines.append(f"Protocol SHA-256 `{args.protocol_sha}`; code `{args.code_sha}`.")
    lines.append("")
    for case in CASES:
        lines.append(f"### Case {LETTER[case]} — {SYMBOL[case]}")
        lines.append("")
        lines.append(
            "| arm | exit reason | entry | exit | net 1x | net 2x | MAE | MFE "
            "| exit (ET) | held s | spread at entry |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for arm in ARMS:
            result = by_key.get((case, arm))
            if result is None:
                lines.append(f"| `{arm}` | NOT RUN | — | — | — | — | — | — | — | — | — |")
                continue
            spread = result.get("spread_at_entry_bps")
            spread_text = f"{spread} bps" if spread else "—"
            lines.append(
                "| `{}` | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    arm,
                    result.get("exit_reason") or "—",
                    result.get("entry_px") or "—",
                    result.get("exit_px") or "—",
                    pct(result.get("net_1x")),
                    pct(result.get("net_2x")),
                    pct(result.get("mae")),
                    pct(result.get("mfe")),
                    when(result.get("exit_ts_ns")),
                    result.get("held_seconds") or "—",
                    spread_text,
                )
            )
        lines.append("")

    lines.append("### Aggregate over the three cases (equal weight, n=3, anecdotal)")
    lines.append("")
    lines.append("| arm | mean net 1x | mean net 2x | mean MAE | mean MFE | exits |")
    lines.append("|---|---|---|---|---|---|")
    for arm in ARMS:
        results = [by_key.get((case, arm)) for case in CASES]
        complete = [r for r in results if r is not None]
        if not complete:
            lines.append(f"| `{arm}` | — | — | — | — | 0/3 |")
            continue
        totals = {
            key: sum(Decimal(str(row[key])) for row in complete) / Decimal(len(complete))
            for key in ("net_1x", "net_2x", "mae", "mfe")
        }
        lines.append(
            "| `{}` | {} | {} | {} | {} | {}/3 |".format(
                arm,
                pct(str(totals["net_1x"])),
                pct(str(totals["net_2x"])),
                pct(str(totals["mae"])),
                pct(str(totals["mfe"])),
                len(complete),
            )
        )
    lines.append("")
    lines.append(
        "Labels: MODELED; n=3 (A, B, C); hindsight-selected; survivor_only; anecdotal; "
        "never merit. Arm 1's exit is a modeled fill on the quote bid at the breach, not a "
        "broker fill. B runs because C1 named its -32.7% exit a modeled fill artifact, not "
        "an ATR corporate-action bug."
    )
    lines.append("")
    if args.bundle:
        lines.append(f"Bundle: `{args.bundle}` SHA-256 `{args.bundle_sha}`")
    else:
        lines.append("Bundle: pending")
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
