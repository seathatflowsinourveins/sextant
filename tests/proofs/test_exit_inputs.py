"""Row 48 keeps #41's input pin and catalog writer after the study moves to its ref.

The study's driver lives on ``research/exit-study-5fe0977`` at the annotated tag
``exit-study-2026-11-10`` (row 46). The recorded-bar replay in
``src/sextant/backtest/replay.py`` still needs the write-up's input hashes and its
Nautilus catalog writer, so those pieces stay on main in
``src/sextant/backtest/exit_inputs.py``, byte-for-byte from the driver. The rest of
the driver and its proofs live on the ref; nothing here imports them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from sextant.backtest import exit_inputs

BARS = "minute-bars-2026-10-26_29.jsonl"
FILLS = "fills-2026-10-26_29.jsonl"
OWNER = "b-owner-first-orders.json"
MINUTE_NS = 60 * 1_000_000_000


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_retained_module_carries_the_write_ups_input_pin() -> None:
    assert exit_inputs.INPUTS == {
        BARS: "105caeee0645455aa0e1de23a1720639347062061944ea3d49eedb6d99a86a69",
        FILLS: "55eee2b64506c19e23d4c421c803be687daf06ebb39a2b84f621ea2a90618c0f",
        OWNER: "5e95de9eaefd9e24cfbd96850ab499fdfa6505e83dcf205ca485584ad5d9e6d3",
    }
    assert exit_inputs.DEFAULT_INPUTS == Path.home() / "sextant-data" / "exit-study-41"


def test_verify_inputs_returns_the_hashes_it_checked(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a").write_text("alpha")
    (tmp_path / "b").write_text("beta")
    pin = {"a": _sha("alpha"), "b": _sha("beta")}
    monkeypatch.setattr(exit_inputs, "INPUTS", pin)
    assert exit_inputs.verify_inputs(tmp_path) == pin


def test_verify_inputs_refuses_a_changed_byte(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a").write_text("alpha")
    monkeypatch.setattr(exit_inputs, "INPUTS", {"a": _sha("alpha")})
    (tmp_path / "a").write_text("alphA")
    with pytest.raises(ValueError, match="inputs differ"):
        exit_inputs.verify_inputs(tmp_path)


def test_write_catalog_writes_one_equity_and_one_minute_series_per_symbol(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "symbol": "AAPL",
            "t": "2026-10-26T13:30:00+00:00",
            "o": "100.0",
            "h": "101.0",
            "l": "99.0",
            "c": "100.5",
            "v": "1000",
            "vw": "100.2",
        },
        {
            "symbol": "MSFT",
            "t": "2026-10-26T13:30:00+00:00",
            "o": "200.0",
            "h": "201.0",
            "l": "199.0",
            "c": "200.5",
            "v": "2000",
            "vw": "200.2",
        },
    ]
    bars = tmp_path / BARS
    bars.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))

    catalog = exit_inputs.write_catalog(bars, tmp_path / "catalog")
    written = sorted(catalog.query_bars(), key=lambda bar: bar.bar_type.instrument_id.symbol.value)

    assert [str(bar.bar_type) for bar in written] == [
        "AAPL.ALPACA-1-MINUTE-LAST-EXTERNAL",
        "MSFT.ALPACA-1-MINUTE-LAST-EXTERNAL",
    ]
    open_ns = int(datetime.fromisoformat("2026-10-26T13:30:00+00:00").timestamp()) * 1_000_000_000
    expected = [("100", "101", "99", "100.5", 1000), ("200", "201", "199", "200.5", 2000)]
    for bar, (o, h, low, c, v) in zip(written, expected, strict=True):
        assert bar.ts_event == open_ns + MINUTE_NS
        assert bar.open.as_decimal() == Decimal(o)
        assert bar.high.as_decimal() == Decimal(h)
        assert bar.low.as_decimal() == Decimal(low)
        assert bar.close.as_decimal() == Decimal(c)
        assert bar.volume.as_decimal() == Decimal(v)
