"""Local replay viewer on the selected Lightweight Charts pin (ADR-0021); display only.

Pure renderer: recorded minute-bar rows (the t/o/h/l/c shape) plus recorded
event dicts (ExitEngine `event` or entry ReplayResult `action`, ns `ts`, Decimal strings)
become one self-contained HTML page. Candles come from the bars; the trail trigger is one
stepped series over the recorded `trigger` values; recorded `entry`, `high`, `gain_lock` and
breach-sell `limit` values are price lines; every event is one marker snapped to its bar,
because a marker whose time matches no data point is dropped silently (upstream SKILL.md:158
at the pin). Nothing is computed here or in the browser: a level no artifact records is
absent, never derived. Decimal strings become display floats only in the embedded JSON.

Source: tradingview/lightweight-charts@v5.2.1 b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1:
dist/typings.d.ts:212 createChart, :294 createSeriesMarkers, :98-104 LineType.WithSteps,
:1640 addSeries, :2541 createPriceLine, :2918 fitContent, :3176 attributionLogo;
.github/skills/lightweight-charts/SKILL.md:179,400-407 (standalone window.LightweightCharts).
Palette: dataviz validate_palette.js, dark ALL PASS, read 2026-11-09; colour follows the
entity (entry/H/trigger/gain-lock/exit), with titles, legend and table as second encoding.
"""

from __future__ import annotations

import bisect
import calendar
import hashlib
import html
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

VENDOR = Path(__file__).resolve().parents[3] / "lanes/tradingview/vendor/lightweight-charts-5.2.1"
BUNDLE = "lightweight-charts.standalone.production.js"
NS = 1_000_000_000
ENTRY, HIGH, TRIGGER, GAIN_LOCK, EXIT, NEUTRAL = (
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#9aa0a6",
)
_MARKERS: dict[str, tuple[str, str, str]] = {  # recorded name -> position, shape, colour
    "protected_from_fill": ("belowBar", "arrowUp", ENTRY),
    "protected_qty": ("belowBar", "arrowUp", ENTRY),
    "entry_fill": ("belowBar", "arrowUp", ENTRY),
    "SUBMIT": ("belowBar", "arrowUp", ENTRY),
    "initial_trigger": ("belowBar", "circle", TRIGGER),
    "crossed": ("belowBar", "circle", TRIGGER),
    "armed": ("belowBar", "circle", GAIN_LOCK),
    "breach_sell_prearm": ("aboveBar", "arrowDown", EXIT),
    "breach_sell_gain_lock": ("aboveBar", "arrowDown", EXIT),
    "sell_fill": ("aboveBar", "arrowDown", EXIT),
    "chase": ("aboveBar", "circle", EXIT),
}
_BOOTSTRAP = """const data = JSON.parse(document.getElementById('replay-data').textContent);
const chart = LightweightCharts.createChart(document.getElementById('chart'), {
  layout: {
    attributionLogo: true,
    background: { type: 'solid', color: '#1a1a19' },
    textColor: '#e8e8e6',
  },
  timeScale: { timeVisible: true, secondsVisible: true },
});
const candles = chart.addSeries(LightweightCharts.CandlestickSeries, {
  upColor: '#e8e8e6', downColor: '#7a7f87', borderVisible: false,
  wickUpColor: '#e8e8e6', wickDownColor: '#7a7f87', title: 'Price',
});
candles.setData(data.candles);
for (const line of data.priceLines) {
  candles.createPriceLine({
    price: line.price, color: line.color, lineWidth: 2, title: line.title,
  });
}
if (data.ratchet.length > 0) {
  const trail = chart.addSeries(LightweightCharts.LineSeries, {
    color: '#199e70', lineWidth: 2,
    lineType: LightweightCharts.LineType.WithSteps, title: 'Trail trigger',
  });
  trail.setData(data.ratchet);
}
LightweightCharts.createSeriesMarkers(candles, data.markers);
chart.timeScale().fitContent();"""


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (Decimal, int, str)):
        raise ValueError(f"recorded {field} must be an exact Decimal value, not {value!r}")
    try:
        exact = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation:
        raise ValueError(f"recorded {field} is not a Decimal value: {value!r}") from None
    if not exact.is_finite():
        raise ValueError(f"recorded {field} is not finite: {value!r}")
    return exact


def _display(value: Decimal, field: str) -> float:  # the one Decimal -> float edge
    shown = float(value)
    if not math.isfinite(shown):
        raise ValueError(f"recorded {field} overflows display precision: {value}")
    return shown


def _open_second(bar: Mapping[str, Any]) -> int:
    text = bar.get("t")
    if not isinstance(text, str):
        raise ValueError("recorded bar t must be an ISO-8601 string")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"recorded bar t is not ISO-8601: {text!r}") from None
    if moment.utcoffset() is None or moment.microsecond:
        raise ValueError(f"recorded bar t needs a UTC offset and whole seconds: {text!r}")
    return calendar.timegm(moment.utctimetuple())


def _candles(bars: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[int]]:
    if not bars:
        raise ValueError("a replay view needs at least one recorded bar")
    candles, opens = [], []
    for bar in bars:
        opens.append(_open_second(bar))
        candles.append(
            {
                "time": opens[-1],
                **{
                    key: _display(_decimal(bar.get(code), code), code)
                    for code, key in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))
                },
            }
        )
    if any(later <= earlier for earlier, later in itertools.pairwise(opens)):
        raise ValueError("recorded bar opens must be unique and ascending")
    return candles, opens


def _events(
    events: Sequence[Mapping[str, Any]],
) -> list[tuple[int, str, Mapping[str, Any]]]:
    rows = []
    for event in events:
        if not all(isinstance(key, str) for key in event):
            raise ValueError("a recorded event needs string field names")
        name = event.get("event") or event.get("action")
        if not isinstance(name, str) or not name:
            raise ValueError("a recorded event needs an event or action name")
        raw = event.get("ts")
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise ValueError("a recorded event needs an integer-nanosecond ts")
        try:
            stamp = int(raw)
        except ValueError:
            raise ValueError(f"recorded event ts is not an integer: {raw!r}") from None
        if not 0 <= stamp // NS <= 253_402_300_799:  # datetime's own range, year 9999
            raise ValueError("recorded event ts is outside the datable range")
        rows.append((stamp, name, event))
    return sorted(rows, key=lambda row: row[0])


def _level(event: Mapping[str, Any], field: str) -> Decimal | None:
    return None if field not in event else _decimal(event[field], field)


def _ratchet(
    rows: list[tuple[int, str, Mapping[str, Any]]], last_open: int
) -> list[dict[str, Any]]:
    points: list[tuple[int, Decimal]] = []
    for stamp, _name, event in rows:
        trigger = _level(event, "trigger")
        if trigger is None:
            continue
        second = stamp // NS
        if points and points[-1][0] == second:
            points[-1] = (second, trigger)  # one time per series point; last recorded wins
        else:
            points.append((second, trigger))
    if points and last_open > points[-1][0]:  # the recorded trigger stays in force to the end
        points.append((last_open, points[-1][1]))
    return [{"time": t, "value": _display(v, "trigger")} for t, v in points]


def _price_lines(
    rows: list[tuple[int, str, Mapping[str, Any]]],
) -> list[tuple[str, str, Decimal]]:
    def first(field: str) -> Decimal | None:
        return next((v for _s, _n, e in rows if (v := _level(e, field)) is not None), None)

    def last(field: str) -> Decimal | None:
        return next(
            (v for _s, _n, e in reversed(rows) if (v := _level(e, field)) is not None), None
        )

    exit_limit = next(
        (
            v
            for _s, n, e in rows
            if n.startswith("breach_sell") and (v := _level(e, "limit")) is not None
        ),
        None,
    )
    wanted = (
        ("Entry", ENTRY, first("entry")),
        ("H", HIGH, last("high")),
        ("Gain lock", GAIN_LOCK, first("gain_lock")),
        ("Exit limit", EXIT, exit_limit),
    )
    return [(title, color, value) for title, color, value in wanted if value is not None]


def _markers(
    rows: list[tuple[int, str, Mapping[str, Any]]], opens: list[int]
) -> list[dict[str, Any]]:
    markers = []
    for stamp, name, _event in rows:
        index = min(max(bisect.bisect_right(opens, stamp // NS) - 1, 0), len(opens) - 1)
        position, shape, color = _MARKERS.get(name, ("inBar", "circle", NEUTRAL))
        markers.append(
            {
                "time": opens[index],
                "position": position,
                "shape": shape,
                "color": color,
                "text": name,
            }
        )
    return markers


def _bundle() -> str:
    recorded = {}
    for line in (VENDOR / "SHA256").read_text().splitlines():
        digest, name = line.split()
        recorded[name] = digest
    bundle = (VENDOR / BUNDLE).read_bytes()
    if hashlib.sha256(bundle).hexdigest() != recorded.get(BUNDLE):
        raise ValueError("vendored bundle differs from its recorded SHA-256")
    return bundle.decode()


def render_replay_html(
    bars: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    title: str = "Recorded replay",
) -> str:
    """One self-contained page for one recorded replay; nothing computed, nothing fetched."""
    bundle = _bundle()
    candles, opens = _candles(bars)
    rows = _events(events)
    ratchet = _ratchet(rows, opens[-1])
    lines = _price_lines(rows)
    data = {
        "candles": candles,
        "markers": _markers(rows, opens),
        "priceLines": [
            {"color": color, "price": _display(value, name), "title": name}
            for name, color, value in lines
        ],
        "ratchet": ratchet,
    }
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    legend = ["<li>Price (recorded bars)</li>"]
    if ratchet:
        legend.append(f'<li style="color:{TRIGGER}">Trail trigger (recorded)</li>')
    legend += [
        f'<li style="color:{color}">{html.escape(name)} {html.escape(str(value))}</li>'
        for name, color, value in lines
    ]
    table = []
    for stamp, name, event in rows:
        when = datetime.fromtimestamp(stamp // NS, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        fields = " ".join(
            f"{key}={event[key]}" for key in sorted(event) if key not in {"ts", "event", "action"}
        )
        table.append(
            f"<tr><td>{when}</td><td>{html.escape(name)}</td><td>{html.escape(fields)}</td></tr>"
        )
    notice = html.escape((VENDOR / "NOTICE").read_text().strip()).replace("\n", "<br>")
    return "\n".join(
        [
            "<!doctype html>",
            '<meta charset="utf-8">',
            f"<title>{html.escape(title)}</title>",
            "<style>body{background:#1a1a19;color:#e8e8e6;font-family:system-ui}"
            "table{border-collapse:collapse}td{border:1px solid #444;padding:2px 8px}</style>",
            f"<h1>{html.escape(title)}</h1>",
            "<ul>" + "".join(legend) + "</ul>",
            '<div id="chart" style="height:480px"></div>',
            "<table>" + "".join(table) + "</table>",
            f"<p>{notice}</p>",
            '<p>Chart library: <a href="https://www.tradingview.com/">TradingView</a>'
            " Lightweight Charts v5.2.1 (Apache-2.0), vendored locally; recorded artifacts"
            " only, no network, no order path.</p>",
            "<script>",
            bundle,
            "</script>",
            '<script type="application/json" id="replay-data">',
            payload.replace("<", "\\u003c"),
            "</script>",
            "<script>",
            _BOOTSTRAP,
            "</script>",
            "",
        ]
    )
