"""R33: replay native VWAP against Decimal before accepting a replacement.

N7 55c0e82053142bce3a5cba4de4221d3929c2d3bc and N8
d53849b216e20f2c122ca01b4dd0da377638b186 have identical average/vwap.rs
and its Python binding: manual update_raw/reset, f64 accumulation.
"""

from decimal import Decimal as D
from importlib.metadata import version

import pytest
from nautilus_trader.indicators import VolumeWeightedAveragePrice

import sextant.entry.replay as engine_replay
from sextant.entry.signals import EntryState

from .conftest import SEC, START, bar, trade
from .test_replay import replay


@pytest.mark.parametrize(
    ("first", "last", "decimal_vwap", "native_vwap", "native_extension"),
    [
        ("10.00", "10.60", "10.20", "10.200000000000001", "NOT_EXTENDED"),
        ("10.01", "10.61", "10.21", "10.209999999999999", "EXTENDED"),
    ],
    ids=["classification-control", "exact-boundary-difference"],
)
def test_native_vwap_paired_replay_requires_a_decimal_exception(
    instrument, tmp_path, monkeypatch, first, last, decimal_vwap, native_vwap, native_extension
):
    assert version("nautilus-trader") in {"2.0.0rc7", "2.0.0rc8"}
    data = [bar(-180), bar(-120), bar(-60), trade(0, first, size=2), trade(1, last, size=1)]
    decimal_arm = replay(instrument, tmp_path / "decimal", data, surge=None)
    observed = []

    class NativeVWAPState(EntryState):
        def __init__(self, *args, **kwargs):
            self.native_vwap = VolumeWeightedAveragePrice()
            super().__init__(*args, **kwargs)

        def reset_segment(self, segment):
            super().reset_segment(segment)
            self.native_vwap.reset()
            self.native_last = None

        def _extension(self, price):
            assert self.last is not None
            if self.last is not self.native_last:
                self.native_vwap.update_raw(
                    float(self.last.price.as_decimal()), float(self.last.size.as_decimal())
                )
                self.native_last = self.last
                observed.append(D(str(self.native_vwap.value)))
            self.vwap = D(str(self.native_vwap.value))
            return super()._extension(price)

    monkeypatch.setattr(engine_replay, "EntryState", NativeVWAPState)
    native_arm = replay(instrument, tmp_path / "native", data, surge=None)
    decimal_rows = [(e["ts"], e["extension"]) for e in decimal_arm.events if e["action"] == "TRADE"]
    native_rows = [(e["ts"], e["extension"]) for e in native_arm.events if e["action"] == "TRADE"]
    assert decimal_rows == [(START, "NOT_EXTENDED"), (START + SEC, "NOT_EXTENDED")]
    assert native_rows == [(START, "NOT_EXTENDED"), (START + SEC, native_extension)]
    assert D(first) * 2 + D(last) == D(decimal_vwap) * 3
    assert observed[-1] == D(native_vwap)
    assert sum(a != b for a, b in zip(decimal_rows, native_rows, strict=True)) == (
        native_extension == "EXTENDED"
    )
    assert decimal_arm.orders == native_arm.orders == []
