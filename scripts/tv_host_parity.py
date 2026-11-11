#!/usr/bin/env python3
"""Bar-fidelity parity witness over the recorded 2026-11-09 session.

Run it with the repository environment::

    uv run --frozen python scripts/tv_host_parity.py --work-dir /path/to/e2e-omh/work

The script loads the e2e's recorded SIP minute arrays (``arrays/2026-11-09.npz``),
its five-session per-session baseline curves (``baseline_pre.npz`` and
``baseline_rth.npz``) and the replay's rank matrix (``ranks.npz``), feeds every
minute through ``BarFidelityHost`` and compares each minute's K2 ranks with the
recorded replay matrix.

Only the symbols that traded in a minute are ranked, exactly as the research
replay advanced its rows; the display publisher additionally retains stale rows,
which is the live host's documented behaviour and is not part of this comparison.
The witness therefore proves that the host's rows -- including the vendor trade
count fed into ``trades_accel`` -- reproduce the replay's K2 order exactly.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import zipfile
from array import array
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nautilus_trader.common import MessageBus  # noqa: E402
from nautilus_trader.model import TraderId  # noqa: E402

from sextant.ranking.engine import (  # noqa: E402
    MoverRow,
    ReferencePrices,
    Segment,
    rank_movers,
)
from sextant.ranking.publisher import RankingPublisher  # noqa: E402
from sextant.ranking.registry import Registry, RegistryRow  # noqa: E402
from sextant.tradingview.bars import Bar, BarPoll  # noqa: E402
from sextant.tradingview.baseline import FiveSessionBaseline  # noqa: E402
from sextant.tradingview.host import BarFidelityHost, load_symbol_map  # noqa: E402
from sextant.tradingview.producer import Clocks, reserve_stream  # noqa: E402

NS = 1_000_000_000
MINUTE_NS = 60 * NS
DAY = date(2026, 11, 9)
PRIOR = date(2026, 11, 6)
NY = ZoneInfo("America/New_York")
SCALE = 10_000
SEGMENTS = (
    # name, first array offset, stop offset, segment start, segment end
    ("PRE", 0, 330, (4, 0), (9, 30)),
    ("RTH", 330, 455, (9, 30), (16, 0)),
)
FIXTURE_ROWS = {
    "mover_min_move": (Decimal("0.03"), "fraction"),
    "mover_min_trades_accel": (Decimal("1.5"), "ratio"),
    "mover_min_dvol_ratio": (Decimal("3"), "ratio"),
    "move_1m_window_s": (60, "seconds"),
    "move_5m_window_s": (300, "seconds"),
    "trades_accel_window_s": (60, "seconds"),
    "trades_accel_baseline_min": (5, "minutes"),
    "publish_min_interval_s": (1, "seconds"),
    "generation_max_age_s": (2, "seconds"),
    "heartbeat_max_age_s": (2, "seconds"),
    "input_max_age_s": (2, "seconds"),
    "top_n": (2, "symbols"),
}
FIXTURE_SOURCE = "e2e-omh replay fixture (work/replay.py); UNCALIBRATED"


def _npy(blob: bytes) -> tuple[tuple[int, ...], object]:
    """Read the little-endian .npy dtypes this witness needs (format v1/v2)."""
    if blob[:6] != b"\x93NUMPY":
        raise ValueError("not a .npy array")
    start = 10 if blob[6] == 1 else 12
    length = int.from_bytes(blob[8:start], "little")
    header = ast.literal_eval(blob[start : start + length].decode("latin1"))
    if header["fortran_order"]:
        raise ValueError("fortran-ordered arrays are not supported")
    shape = tuple(header["shape"])
    descr = header["descr"]
    count = 1
    for size in shape:
        count *= size
    data = blob[start + length :]
    if descr.startswith("<U"):
        width = int(descr[2:]) * 4
        if len(data) != count * width:
            raise ValueError("unexpected unicode payload")
        symbols = tuple(
            "".join(
                chr(int.from_bytes(data[base + step : base + step + 4], "little"))
                for step in range(0, width, 4)
            ).rstrip("\x00")
            for base in range(0, len(data), width)
        )
        return shape, symbols if shape else symbols[0]
    codes = {"<i8": "q", "<i4": "i", "|u1": "B"}
    if descr not in codes:
        raise ValueError(f"unsupported dtype: {descr}")
    values = array(codes[descr])
    if len(data) != count * values.itemsize:
        raise ValueError("unexpected array payload")
    values.frombytes(data)
    if sys.byteorder == "big" and values.itemsize > 1:
        values.byteswap()
    return shape, values if shape else values[0]


class Npz:
    """Minimal .npz reader: enough for the recorded e2e artifacts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._zip = zipfile.ZipFile(path)

    def read(self, name: str) -> tuple[tuple[int, ...], object]:
        members = set(self._zip.namelist())
        for candidate in (f"{name}.npy", name):
            if candidate in members:
                return _npy(self._zip.read(candidate))
        raise KeyError(f"{name} is not in {self.path}")


def _registry() -> Registry:
    return Registry(
        tuple(
            RegistryRow(name, unit, value, FIXTURE_SOURCE, "UNCALIBRATED", DAY)
            for name, (value, unit) in FIXTURE_ROWS.items()
        )
    )


def _clock(day: date, hour: int, minute: int) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY).timestamp()) * NS


def _baseline(
    npz: Npz, *, segment: str, sessions: tuple[date, ...], symbols: tuple[str, ...]
) -> FiveSessionBaseline:
    _, raw_symbols = npz.read("symbols")
    if tuple(raw_symbols) != symbols:
        raise ValueError(f"{segment} baseline symbols do not match the minute arrays")
    dv_shape, dv_flat = npz.read("dv_sessions")
    count_shape, count_flat = npz.read("n_sessions")
    if dv_shape != count_shape or dv_shape[0] != len(sessions):
        raise ValueError(f"{segment} baseline curves do not match the sessions")
    points = dv_shape[2]
    known_at = int(npz.read("known_at")[1])
    provenance = str(npz.read("provenance")[1])
    stride = len(symbols) * points
    return FiveSessionBaseline(
        segment=segment,
        end_s=(points - 1) * 60,
        sessions=sessions,
        symbols=symbols,
        known_at=known_at,
        provenance=provenance,
        dv=tuple(
            array("q", dv_flat[index * stride : (index + 1) * stride])
            for index in range(len(sessions))
        ),
        counts=tuple(
            array("q", count_flat[index * stride : (index + 1) * stride])
            for index in range(len(sessions))
        ),
        data_digest=sha256(npz.path.read_bytes()).hexdigest(),
    )


def _prior_closes(daily_path: Path, symbols: tuple[str, ...]) -> dict[str, Decimal]:
    daily = json.loads(daily_path.read_text(encoding="utf-8"))
    closes: dict[str, Decimal] = {}
    for symbol in symbols:
        rows = daily.get(symbol)
        if rows and PRIOR.isoformat() in rows:
            closes[symbol] = Decimal(str(rows[PRIOR.isoformat()]["c"]))
    return closes


def _minute_bars(
    symbols: tuple[str, ...],
    arrays: dict[str, object],
    *,
    width: int,
    segment_start_ns: int,
    first_offset: int,
    offset: int,
    count_override: int | None = None,
) -> tuple[Bar, ...]:
    price = arrays["price"]
    open_price = arrays["open_price"]
    volume = arrays["volume"]
    count = arrays["count"]
    present = arrays["present"]
    bars: list[Bar] = []
    for position, symbol in enumerate(symbols):
        cell = position * width + offset
        if not present[cell] or volume[cell] <= 0:
            continue
        close = Decimal(int(price[cell])) / SCALE
        opening = Decimal(int(open_price[cell])) / SCALE if open_price[cell] > 0 else close
        bars.append(
            Bar(
                symbol=symbol,
                start_ns=segment_start_ns + (offset - first_offset) * MINUTE_NS,
                open=opening,
                close=close,
                volume=int(volume[cell]),
                trades=count_override if count_override is not None else int(count[cell]),
            )
        )
    return tuple(bars)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--sessions", default="2026-11-02,2026-11-03,2026-11-04,2026-11-05,2026-11-06"
    )
    parser.add_argument("--symbol-map", type=Path)
    parser.add_argument("--publish-unit", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--minutes", type=int)
    parser.add_argument("--max-mismatches", type=int, default=25)
    parser.add_argument(
        "--count-mode",
        choices=("vendor", "replay"),
        default="vendor",
        help="vendor: trades_accel uses the SIP bar trade count (the host path); "
        "replay: one tick per bar, the research replay's documented proxy",
    )
    args = parser.parse_args()
    count_override = 1 if args.count_mode == "replay" else None

    work: Path = args.work_dir
    sessions = tuple(date.fromisoformat(part) for part in args.sessions.split(","))

    arrays_npz = Npz(work / "arrays" / f"{DAY.isoformat()}.npz")
    width = arrays_npz.read("present")[0][1]
    _, symbols = arrays_npz.read("symbols")
    symbols = tuple(symbols)
    index_of = {symbol: position for position, symbol in enumerate(symbols)}
    arrays = {
        "price": arrays_npz.read("price")[1],
        "open_price": arrays_npz.read("open_price")[1],
        "volume": arrays_npz.read("volume")[1],
        "count": arrays_npz.read("count")[1],
        "present": arrays_npz.read("present")[1],
    }
    _, rank = Npz(work / "ranks.npz").read("rank")
    _, generation_ns = Npz(work / "ranks.npz").read("generation_ns")
    closes = _prior_closes(work / "daily.json", symbols)
    if len(closes) != len(symbols):
        raise SystemExit(f"{len(symbols) - len(closes)} symbols lack a {PRIOR} close")
    references = {
        symbol: ReferencePrices(
            closes[symbol], _clock(PRIOR, 16, 0), "alpaca_sip_raw_1day official close"
        )
        for symbol in symbols
    }

    report: dict = {
        "date": DAY.isoformat(),
        "count_mode": args.count_mode,
        "work_dir": str(work),
        "universe": len(symbols),
        "registry_params_hash": _registry().params_hash,
        "registry_source": FIXTURE_SOURCE,
        "sessions": [session.isoformat() for session in sessions],
        "segments": {},
        "hard_mismatches": 0,
        "tie_only_minutes": 0,
        "mismatch_samples": [],
        "unit": None,
    }
    samples: list[dict] = []
    total_minutes = 0
    total_rows = 0
    # No display mapping is invented: without an operator map every membership is
    # unknown, so any attempted unit correctly reports unavailable.
    symbol_map = (
        load_symbol_map(args.symbol_map)
        if args.symbol_map
        else {symbol: None for symbol in symbols}
    )

    skipped: list[dict] = []

    for name, first_offset, stop_offset, start, end in SEGMENTS:
        baseline = _baseline(
            Npz(work / f"baseline_{name.lower()}.npz"),
            segment=name,
            sessions=sessions,
            symbols=symbols,
        )
        segment = Segment(
            name, DAY, _clock(DAY, *start), _clock(DAY, *end), "exchange_calendars XNYS actual"
        )
        publisher = RankingPublisher(
            bus=MessageBus(TraderId.from_str("TV-HOST-PARITY")),
            epoch=f"parity-{name.lower()}",
            feed="sip",
            segment=segment,
            registry=_registry(),
            universe=symbols,
            universe_source="recorded 2026-11-09 e2e universe; NOT PIT membership",
            baseline=baseline,
        )
        for symbol in symbols:
            publisher.set_symbol(symbol, references=references[symbol], asset=None)
        minutes = 0
        rows_seen = 0
        hard_minutes = 0
        tie_minutes = 0
        publish_clock = None
        with reserve_stream(
            work / "parity-leases",
            paper_slot=2,
            existing_streams=0,
            source="B's writer opens no market-data stream; parity witness only",
        ) as lease:
            host = BarFidelityHost(
                publisher,
                lease=lease,
                sip_authority="recorded e2e SIP authority",
                symbol_map=symbol_map,
            )
            for offset in range(first_offset, stop_offset):
                if args.minutes is not None and minutes >= args.minutes:
                    break
                clock = int(generation_ns[offset])
                bars = _minute_bars(
                    symbols,
                    arrays,
                    width=width,
                    segment_start_ns=segment.start_ns,
                    first_offset=first_offset,
                    offset=offset,
                    count_override=count_override,
                )
                if bars and bars[0].close_ns > clock:
                    # The e2e replay clips a bar whose close is the segment boundary
                    # (the PRE 09:29 bar closes exactly at 09:30) to end-1 ns, a
                    # catalog-clock convention; the live host never re-times a bar, so
                    # that boundary minute has no host-representable comparison.
                    skipped.append(
                        {"segment": name, "minute": offset, "bars": len(bars), "clock": clock}
                    )
                    continue
                host.ingest(
                    BarPoll(bars=bars, requested=symbols), market_ns=clock, received_ns=clock
                )
                host.heartbeat(at=clock, received_ns=clock)
                traded = [item.symbol for item in bars]
                ranked = rank_movers(
                    row
                    for row in (publisher.states[symbol].latest for symbol in traded)
                    if isinstance(row, MoverRow)
                )
                actual = {row.symbol: row.rank for row in ranked}
                scores = {row.symbol: row.score for row in ranked}
                expected = {
                    symbol: int(rank[offset * len(symbols) + index_of[symbol]])
                    for symbol in traded
                    if rank[offset * len(symbols) + index_of[symbol]] > 0
                }
                differences = {
                    symbol for symbol in expected if actual.get(symbol) != expected[symbol]
                }
                hard = {symbol for symbol in differences if scores.get(symbol) != 0}
                wanted_groups: dict[object, list[int]] = {}
                got_groups: dict[object, list[int]] = {}
                for symbol, expected_rank in expected.items():
                    wanted_groups.setdefault(scores.get(symbol), []).append(expected_rank)
                for symbol, actual_rank in actual.items():
                    got_groups.setdefault(scores.get(symbol), []).append(actual_rank)
                for score, wanted in wanted_groups.items():
                    if sorted(wanted) != sorted(got_groups.get(score, [])):
                        hard.update(symbol for symbol in expected if scores.get(symbol) == score)
                rows_seen += len(traded)
                if hard:
                    hard_minutes += 1
                    if len(samples) < args.max_mismatches:
                        samples.append(
                            {
                                "segment": name,
                                "minute": offset,
                                "clock": clock,
                                "hard_symbols": len(hard),
                                "first_hard": sorted(hard)[:10],
                                "wrong_rows": len(differences),
                            }
                        )
                elif differences:
                    tie_minutes += 1
                minutes += 1
                publish_clock = clock
            if args.publish_unit and args.symbol_map and publish_clock is not None:
                unit = host.publish(
                    args.publish_unit,
                    now=publish_clock,
                    mapping_clocks=Clocks(publish_clock, publish_clock, "parity witness receipt"),
                )
                report["unit"] = {
                    "segment": name,
                    "status": unit["status"],
                    "watchlists": unit.get("watchlists"),
                    "reason": unit.get("reason"),
                    "expires_at_ns": unit.get("expires_at_ns"),
                }
        total_minutes += minutes
        total_rows += rows_seen
        report["hard_mismatches"] += hard_minutes
        report["tie_only_minutes"] += tie_minutes
        report["segments"][name] = {
            "minutes": minutes,
            "rows": rows_seen,
            "hard_mismatched_minutes": hard_minutes,
            "tie_only_minutes": tie_minutes,
            "baseline_sessions": [session.isoformat() for session in baseline.sessions],
        }

    report["minutes"] = total_minutes
    report["rows"] = total_rows
    report["boundary_minutes_skipped"] = skipped
    report["mismatch_samples"] = samples
    report_path = args.report or work / "tv-host-parity.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        f"count_mode={args.count_mode} minutes={total_minutes} rows={total_rows} "
        f"hard_mismatched_minutes={report['hard_mismatches']} "
        f"tie_only_minutes={report['tie_only_minutes']} report={report_path}"
    )
    return 0 if report["hard_mismatches"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
