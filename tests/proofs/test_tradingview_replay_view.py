"""Local replay viewer witnesses (TV reconcile PR-1, ADR-0021): recorded artifacts only.

Source: tradingview/lightweight-charts@v5.2.1 b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1,
dist/typings.d.ts:212 (createChart), :294 (createSeriesMarkers), :98-104 (LineType.WithSteps),
:2541 (createPriceLine), :3176 (attributionLogo); .github/skills/lightweight-charts/SKILL.md:158
(marker time must match a data point), :179,400-407 (standalone window.LightweightCharts).
Fixtures use the recorded shapes: recorded minute-bar rows (t/o/h/l/c) and ExitEngine
event dicts (ts as digit string, Decimal strings). Browser pixels are not claimed here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from sextant.tradingview import replay_view

ROOT = Path(__file__).parents[2]
VENDOR = ROOT / "lanes/tradingview/vendor/lightweight-charts-5.2.1"
BUNDLE = "lightweight-charts.standalone.production.js"
BUNDLE_SHA256 = "e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf"
GOLDEN_SHA256 = "b863fa72723187763e8e737e171a2cf989aded7d6b5039ea959f75363c0415f5"
NS = 1_000_000_000
T0 = int(datetime(2026, 10, 26, 14, 30, tzinfo=UTC).timestamp())

BARS: list[dict[str, Any]] = [
    {"t": "2026-10-26T14:30:00+00:00", "o": "10.00", "h": "10.20", "l": "9.95", "c": "10.10"},
    {"t": "2026-10-26T14:31:00+00:00", "o": "10.10", "h": "10.50", "l": "10.05", "c": "10.40"},
    {"t": "2026-10-26T14:32:00+00:00", "o": "10.40", "h": "10.45", "l": "10.00", "c": "10.05"},
    {"t": "2026-10-26T14:33:00+00:00", "o": "10.05", "h": "10.10", "l": "10.00", "c": "10.08"},
]


def _event(offset_s: int, name: str, **fields: str) -> dict[str, Any]:
    return {"ts": str((T0 + offset_s) * NS), "event": name, **fields}


EVENTS: list[dict[str, Any]] = [
    _event(5, "protected_from_fill", entry="10.02", qty="100"),
    _event(5, "initial_trigger", trigger="9.90", buffer="0.12"),
    _event(70, "armed", gain_lock="10.15", high="10.50"),
    _event(140, "crossed", trigger="10.15", armed="True"),
    _event(141, "breach_sell_gain_lock", trigger="10.15", limit="10.04", qty="100"),
    _event(150, "sell_fill", price="10.03", qty="100"),
    _event(151, "flat"),
]


def _data(html: str) -> dict[str, Any]:
    body = html.split('<script type="application/json" id="replay-data">', 1)[1]
    return json.loads(body.split("</script>", 1)[0])


def test_vendored_bundle_matches_its_recorded_sha256() -> None:
    recorded = {}
    for line in (VENDOR / "SHA256").read_text().splitlines():
        digest, name = line.split()
        recorded[name] = digest
    assert set(recorded) == {BUNDLE, "LICENSE", "NOTICE"}
    for name, digest in recorded.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest
    bundle = (VENDOR / BUNDLE).read_bytes()
    assert recorded[BUNDLE] == BUNDLE_SHA256
    assert len(bundle) == 197_922
    assert bundle.count(b"\n") + (0 if bundle.endswith(b"\n") else 1) == 7
    assert b"TradingView Lightweight Charts" in bundle[:200]
    assert b"v5.2.1" in bundle[:200] and b"Apache License 2.0" in bundle[:200]
    assert "Apache License" in (VENDOR / "LICENSE").read_text()
    assert "tradingview.com" in (VENDOR / "NOTICE").read_text()


def test_view_emits_every_event_as_a_marker_and_every_level_as_its_own_primitive() -> None:
    html = replay_view.render_replay_html(BARS, EVENTS, title="Fixture replay")
    data = _data(html)
    assert data["candles"] == [
        {"close": 10.1, "high": 10.2, "low": 9.95, "open": 10.0, "time": T0},
        {"close": 10.4, "high": 10.5, "low": 10.05, "open": 10.1, "time": T0 + 60},
        {"close": 10.05, "high": 10.45, "low": 10.0, "open": 10.4, "time": T0 + 120},
        {"close": 10.08, "high": 10.1, "low": 10.0, "open": 10.05, "time": T0 + 180},
    ]
    assert data["ratchet"] == [
        {"time": T0 + 5, "value": 9.9},
        {"time": T0 + 140, "value": 10.15},
        {"time": T0 + 141, "value": 10.15},
        {"time": T0 + 180, "value": 10.15},
    ]
    assert data["priceLines"] == [
        {"color": "#3987e5", "price": 10.02, "title": "Entry"},
        {"color": "#d95926", "price": 10.5, "title": "H"},
        {"color": "#c98500", "price": 10.15, "title": "Gain lock"},
        {"color": "#d55181", "price": 10.04, "title": "Exit limit"},
    ]
    markers = data["markers"]
    assert [m["text"] for m in markers] == [e["event"] for e in EVENTS]
    assert [m["time"] for m in markers] == [T0, T0, T0 + 60, T0 + 120, T0 + 120, T0 + 120, T0 + 120]
    assert markers[0] == {
        "color": "#3987e5",
        "position": "belowBar",
        "shape": "arrowUp",
        "text": "protected_from_fill",
        "time": T0,
    }
    assert markers[4]["position"] == "aboveBar" and markers[4]["shape"] == "arrowDown"
    assert markers[4]["color"] == "#d55181"
    assert markers[6]["position"] == "inBar" and markers[6]["shape"] == "circle"
    for api in (
        "LightweightCharts.createChart",
        "CandlestickSeries",
        "LineSeries",
        "LineType.WithSteps",
        "createPriceLine",
        "createSeriesMarkers",
        "attributionLogo",
    ):
        assert api in html
    assert "Entry 10.02" in html and "Trail trigger" in html  # legend with recorded values
    for event in EVENTS:  # table-view twin lists every recorded event
        assert event["event"] in html
    assert "2026-10-26T14:30:05Z" in html


def test_self_contained_html_has_no_network_reference() -> None:
    html = replay_view.render_replay_html(BARS, EVENTS)
    bundle = (VENDOR / BUNDLE).read_text()
    assert bundle in html  # inlined verbatim; no src fetch
    outside = html.replace(bundle, "", 1)
    for banned in ("src=", "<link", "fetch(", "WebSocket", "XMLHttpRequest", "http://"):
        assert banned not in outside
    assert set(re.findall(r"https://([^/\"<\s]+)", outside)) == {"www.tradingview.com"}
    assert 'href="https://www.tradingview.com/"' in outside  # NOTICE attribution link
    assert "TradingView Lightweight Charts" in outside  # NOTICE text kept on the page
    assert html.count("</script>") == 3


def test_fixture_render_is_byte_stable() -> None:
    first = replay_view.render_replay_html(BARS, EVENTS, title="Fixture replay")
    assert first == replay_view.render_replay_html(BARS, EVENTS, title="Fixture replay")
    assert hashlib.sha256(first.encode()).hexdigest() == GOLDEN_SHA256


def test_action_shaped_entry_events_render_markers() -> None:
    events = [
        {"action": "SUBMIT", "ts": (T0 + 3) * NS, "limit": "10.05"},
        {"action": "FAIL", "ts": (T0 + 90) * NS, "reason": "fixture"},
    ]
    data = _data(replay_view.render_replay_html(BARS, events))
    assert [m["text"] for m in data["markers"]] == ["SUBMIT", "FAIL"]
    assert [m["time"] for m in data["markers"]] == [T0, T0 + 60]
    assert data["ratchet"] == [] and data["priceLines"] == []


def test_no_recorded_trigger_or_high_fabricates_nothing() -> None:
    events = [_event(5, "protected_from_fill", entry="10.02", qty="100"), _event(90, "flat")]
    data = _data(replay_view.render_replay_html(BARS, events))
    assert data["ratchet"] == []
    assert [line["title"] for line in data["priceLines"]] == ["Entry"]
    empty = _data(replay_view.render_replay_html(BARS, []))
    assert empty["markers"] == [] and empty["ratchet"] == [] and empty["priceLines"] == []
    assert len(empty["candles"]) == 4


def test_decreasing_recorded_trigger_is_drawn_as_recorded() -> None:
    events = [
        _event(5, "initial_trigger", trigger="10.00", buffer="0.10"),
        _event(65, "crossed", trigger="9.50", armed="False"),
    ]
    data = _data(replay_view.render_replay_html(BARS, events))
    assert [p["value"] for p in data["ratchet"]] == [10.0, 9.5, 9.5]


def test_event_outside_bars_clamps_marker_but_keeps_ratchet_second() -> None:
    events = [_event(-30, "initial_trigger", trigger="9.90", buffer="0.12")]
    data = _data(replay_view.render_replay_html(BARS, events))
    assert data["markers"][0]["time"] == T0
    assert data["ratchet"][0] == {"time": T0 - 30, "value": 9.9}


def test_recorded_text_cannot_break_out_of_the_page() -> None:
    events = [{"action": "FAIL", "ts": (T0 + 3) * NS, "reason": "</script><b>x</b>"}]
    html = replay_view.render_replay_html(BARS, events, title="<b>Fixture</b>")
    assert html.count("</script>") == 3
    assert "&lt;/script&gt;" in html and "&lt;b&gt;Fixture&lt;/b&gt;" in html


@pytest.mark.parametrize(
    "bars,events",
    [
        ([], []),  # empty bars
        ([{**BARS[0], "o": 10.0}], []),  # float price
        ([{**BARS[0], "o": True}], []),  # bool price
        ([{**BARS[0], "o": "NaN"}], []),  # non-finite
        ([{**BARS[0], "o": Decimal("Infinity")}], []),  # non-finite Decimal
        ([{**BARS[0], "t": "2026-10-26T14:30:00"}], []),  # naive timestamp
        ([BARS[0], BARS[0]], []),  # duplicate open
        ([BARS[1], BARS[0]], []),  # unsorted
        (BARS, [{"event": "flat"}]),  # missing ts
        (BARS, [{"ts": str(T0 * NS)}]),  # missing name
        (BARS, [{"event": "flat", "ts": True}]),  # bool ts
        (BARS, [{"event": "flat", "ts": str(10**30)}]),  # undatable ts
        (BARS, [{"event": "flat", "ts": str(T0 * NS), 7: "x"}]),  # non-string field name
        (BARS, [{"event": "crossed", "ts": str(T0 * NS), "trigger": 9.9}]),  # float level
    ],
)
def test_unusable_recorded_input_is_refused(bars: Any, events: Any) -> None:
    with pytest.raises(ValueError):
        replay_view.render_replay_html(bars, events)


def test_tampered_bundle_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (BUNDLE, "LICENSE", "NOTICE", "SHA256"):
        shutil.copy(VENDOR / name, tmp_path / name)
    path = tmp_path / BUNDLE
    path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(replay_view, "VENDOR", tmp_path)
    with pytest.raises(ValueError, match="bundle"):
        replay_view.render_replay_html(BARS, [])
