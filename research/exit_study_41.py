"""Design row 7's proof: the 96-variant exit study, rerun from the catalog on its exact inputs.

The study is northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
scripts/research/b_exit_replay.py, vendored verbatim as research/b_exit_replay.py (SHA-256
STUDY_SHA256)
and run unmodified. Its write-up is docs/research/2026-10-29-b-exit-replay.md at the same commit.

What this module adds, and nothing else:
- refuses inputs whose SHA-256 differs from the write-up's;
- writes the bars into a NautilusTrader ParquetDataCatalog (v2.0.0rc7 55c0e820, Rust-backed) and
  reads them back. Nautilus `Bar` carries OHLCV and no VWAP, so `vw` is joined from the same
  hash-checked file by (symbol, minute). The catalog's bars must equal the study's own loader
  output, or the run stops;
- hands those bars to the study's `run()` through its `load_bars` seam;
- writes one trial row per arm (96 variants plus hold_flat and actual_fifo) for the ledger
  (ADR-0018), tier MODELED: a minute-bar replay, not a Nautilus fill simulation.

Scanner snapshots were not supplied, so the study's optional spread part (Part 3) does not run.
The study reads them through northstar_trading.scanner.day_files; a stub here refuses any call.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import types
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import (
    Bar,
    BarType,
    Currency,
    Equity,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog

STUDY_SHA256 = "143ab1dd4356e513c6b69d16928fdf594739f62ba170a87bfd6cd384eb99725a"
STUDY = (
    "northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:scripts/research/b_exit_replay.py"
)
BARS, FILLS, OWNER = (
    "minute-bars-2026-10-26_29.jsonl",
    "fills-2026-10-26_29.jsonl",
    "b-owner-first-orders.json",
)
INPUTS = {  # the write-up's own table, docs/research/2026-10-29-b-exit-replay.md lines 23-25
    BARS: "105caeee0645455aa0e1de23a1720639347062061944ea3d49eedb6d99a86a69",
    FILLS: "55eee2b64506c19e23d4c421c803be687daf06ebb39a2b84f621ea2a90618c0f",
    OWNER: "5e95de9eaefd9e24cfbd96850ab499fdfa6505e83dcf205ca485584ad5d9e6d3",
}
DEFAULT_INPUTS = Path.home() / "sextant-data" / "exit-study-41"
VENUE = "ALPACA"
PRICE_PRECISION, SIZE_PRECISION = 4, 1
MINUTE_NS = 60 * 1_000_000_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(folder: Path) -> dict[str, str]:
    found = {name: sha256(folder / name) for name in INPUTS}
    if found != INPUTS:
        raise ValueError(f"inputs differ from the study's recorded SHA-256: {found}")
    return found


def load_study() -> types.ModuleType:
    """Import the verbatim study with its snapshot reader stubbed to refuse."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("scanner snapshots were not supplied (#41); Part 3 does not run")

    stub = types.ModuleType("northstar_trading.scanner.day_files")
    stub.day_file_path = stub.day_files = stub.read_day_json = refuse  # type: ignore[attr-defined]
    sys.modules.setdefault("northstar_trading", types.ModuleType("northstar_trading"))
    sys.modules.setdefault(
        "northstar_trading.scanner", types.ModuleType("northstar_trading.scanner")
    )
    sys.modules["northstar_trading.scanner.day_files"] = stub
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module = importlib.import_module("research.b_exit_replay")
    if sha256(Path(module.__file__ or "")) != STUDY_SHA256:
        raise ValueError("the vendored study is not the pinned file")
    return module


def _rows(bars_path: Path) -> list[dict[str, Any]]:
    with bars_path.open() as stream:
        return [json.loads(line, parse_float=Decimal) for line in stream if line.strip()]


def _open_ns(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp()) * 1_000_000_000


def _text(value: object, places: int) -> str:
    """Exact text at the instrument's precision; refuses a value that would need rounding."""
    exact = Decimal(str(value))
    text = f"{exact:.{places}f}"
    if Decimal(text) != exact:
        raise ValueError(f"{value} does not fit {places} decimals")
    return text


def write_catalog(bars_path: Path, root: Path) -> ParquetDataCatalog:
    """One Equity and one 1-minute EXTERNAL bar series per symbol, stamped at bar close."""
    root.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(root))
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(bars_path):
        by_symbol[row["symbol"]].append(row)
    for symbol, rows in sorted(by_symbol.items()):
        instrument_id = InstrumentId.from_str(f"{symbol}.{VENUE}")
        catalog.write_instruments(
            [
                Equity(
                    instrument_id,
                    Symbol(symbol),
                    Currency.from_str("USD"),
                    PRICE_PRECISION,
                    Price.from_str("0.0001"),
                    0,
                    0,
                )
            ]
        )
        bar_type = BarType.from_str(f"{symbol}.{VENUE}-1-MINUTE-LAST-EXTERNAL")
        bars = []
        for row in sorted(rows, key=lambda r: r["t"]):
            close_ns = _open_ns(row["t"]) + MINUTE_NS
            o, h, low, c = (_text(row[k], PRICE_PRECISION) for k in "ohlc")
            bars.append(
                Bar(
                    bar_type,
                    Price.from_str(o),
                    Price.from_str(h),
                    Price.from_str(low),
                    Price.from_str(c),
                    Quantity.from_str(_text(row["v"], SIZE_PRECISION)),
                    close_ns,
                    close_ns,
                )
            )
        catalog.write_bars(bars)
    return catalog


def catalog_bars(catalog: ParquetDataCatalog, bars_path: Path, study: types.ModuleType) -> dict:
    """The study's Bar rows, built from the catalog's OHLCV plus the source's vw."""
    vw = {(r["symbol"], _open_ns(r["t"])): Decimal(str(r["vw"])) for r in _rows(bars_path)}
    result: dict[str, list] = defaultdict(list)
    for bar in catalog.query_bars():
        symbol = bar.bar_type.instrument_id.symbol.value
        open_ns = bar.ts_event - MINUTE_NS
        at = datetime.fromtimestamp(open_ns // 1_000_000_000, tz=UTC)
        result[symbol].append(
            study.Bar(
                symbol,
                at,
                bar.open.as_decimal(),
                bar.high.as_decimal(),
                bar.low.as_decimal(),
                bar.close.as_decimal(),
                bar.volume.as_decimal(),
                vw[(symbol, open_ns)],
            )
        )
    return {symbol: sorted(rows, key=lambda b: b.at) for symbol, rows in result.items()}


def trial_rows(report: dict, inputs: dict[str, str]) -> list[dict[str, Any]]:
    """One row per arm on the primary 1,025-entry cohort, at 3 and 6 bps per side."""
    selected = report["decision"]["recommended"]
    rows = []
    for arm, summary in report["summaries"].items():
        base, stress = summary["primary"]["combined"]["3"], summary["primary"]["combined"]["6"]
        rows.append(
            {
                "arm": arm,
                "kind": "baseline" if arm in ("hold_flat", "actual_fifo") else "variant",
                "tier": "MODELED",
                "study": f"{STUDY} sha256:{STUDY_SHA256}",
                "version": report["version"],
                "inputs": inputs,
                "cohort": "primary complete-horizon entries, 2026-10-26..28",
                "n": base["entries"],
                "mean_bps_3": str(base["mean_bps"]),
                "mean_bps_6": str(stress["mean_bps"]),
                "median_bps_3": str(base["median_bps"]),
                "median_bps_6": str(stress["median_bps"]),
                "win_rate_3": str(base["win_rate"]),
                "win_rate_6": str(stress["win_rate"]),
                "worst_mae_bps": str(base["max_adverse_excursion_bps"]),
                "mean_mae_bps": str(base["mean_mae_bps"]),
                "pnl_units_3": str(base["total_pnl_unit_notional"]),
                "pnl_units_6": str(stress["total_pnl_unit_notional"]),
                "share_before_flat": str(base["share_exited_before_flat"]),
                "selected": arm == selected,
            }
        )
    return rows


def table(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The write-up's Appendix A cells, at its printed precision."""

    def q(value: str, places: str = "0.01") -> str:
        return f"{Decimal(value).quantize(Decimal(places)):f}"

    def pct(value: str) -> str:
        return q(str(Decimal(value) * 100))

    return {
        r["arm"]: [
            str(r["n"]),
            q(r["mean_bps_3"]),
            q(r["mean_bps_6"]),
            q(r["median_bps_3"]),
            q(r["median_bps_6"]),
            pct(r["win_rate_3"]),
            pct(r["win_rate_6"]),
            q(r["worst_mae_bps"]),
            q(r["mean_mae_bps"]),
            q(r["pnl_units_3"], "0.0001"),
            q(r["pnl_units_6"], "0.0001"),
            pct(r["share_before_flat"]),
        ]
        for r in rows
    }


def published_table(path: Path) -> dict[str, list[str]]:
    lines = path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| Variant | n | Mean 3"))
    rows = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows[cells[0]] = cells[1:]
    return rows


def rerun(inputs: Path, out: Path) -> tuple[dict, list[dict[str, Any]]]:
    hashes = verify_inputs(inputs)
    study: Any = load_study()
    bars_path = inputs / BARS
    catalog = write_catalog(bars_path, out / "catalog")
    bars = catalog_bars(catalog, bars_path, study)
    if bars != study.load_bars(bars_path):
        raise ValueError("catalog bars differ from the study's own loader")
    loader = study.load_bars
    study.load_bars = lambda _path: bars  # the study's own seam; the file is unchanged
    try:
        report = study.run(bars_path, inputs / FILLS, inputs / OWNER, None)
    finally:
        study.load_bars = loader
    rows = trial_rows(report, hashes)
    (out / "replay.json").write_text(
        json.dumps(report, default=study.json_default, indent=2) + "\n"
    )
    (out / "trials.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    return report, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--out", type=Path, default=Path("reports/exit-study-41"))
    args = parser.parse_args()
    _report, rows = rerun(args.inputs, args.out)
    hold = next(r for r in rows if r["arm"] == "hold_flat")
    beaten = sum(
        Decimal(r["mean_bps_3"]) >= Decimal(hold["mean_bps_3"])
        for r in rows
        if r["kind"] == "variant"
    )
    print(
        json.dumps({"arms": len(rows), "variants_at_or_above_hold": beaten, "out": str(args.out)})
    )


if __name__ == "__main__":
    main()
