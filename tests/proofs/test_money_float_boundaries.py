"""Money stays typed: Decimal crosses to float only at named display or SDK edges.

The hard line is AGENTS.md's "Price, Quantity and Money types or Decimal, never floats".
This proof keeps the exception list exact: a new `float` in src fails until it is named
with its reason and source here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/sextant"

# Every allowed site: exact stripped source line -> (reason, source).
ALLOWED: dict[tuple[str, str], tuple[str, str]] = {
    (
        "src/sextant/tradingview/replay_view.py",
        "def _display(value: Decimal, field: str) -> float:  # the one Decimal -> float edge",
    ): (
        "TradingView chart JSON accepts only finite numbers",
        "TradingView Lightweight Charts data contract",
    ),
    (
        "src/sextant/tradingview/replay_view.py",
        "shown = float(value)",
    ): (
        "display-only rendering, checked finite before use",
        "TradingView Lightweight Charts data contract",
    ),
    (
        "src/sextant/tradingview/sync.py",
        "interval: float = 0.75,",
    ): ("wall-clock poll interval, not money", "TradingView sync schedule"),
    (
        "src/sextant/execution/alpaca_transport.py",
        "timeout_s: float = 10.0,",
    ): ("HTTP timeout in seconds, mirroring the vendor client", "alpaca-py transport signature"),
    (
        "src/sextant/research/detectors/page_hinkley.py",
        "converted = float(value)",
    ): ("dimensionless detector statistic", "Page-Hinkley research detector"),
    (
        "src/sextant/research/detectors/page_hinkley.py",
        'delta=float(str(values["delta"])),',
    ): ("dimensionless detector parameter", "Page-Hinkley research detector"),
    (
        "src/sextant/research/detectors/page_hinkley.py",
        'threshold=float(str(values["threshold"])),',
    ): ("dimensionless detector parameter", "Page-Hinkley research detector"),
    (
        "src/sextant/research/detectors/page_hinkley.py",
        'alpha=float(str(values["alpha"])),',
    ): ("dimensionless detector parameter", "Page-Hinkley research detector"),
    (
        "src/sextant/research/detectors/page_hinkley.py",
        "value = float(str(observation.value))  # Only dimensionless "
        "statistical input, never money.",
    ): ("dimensionless observation, explicitly never money", "Page-Hinkley research detector"),
    (
        "src/sextant/research/exit_grid_141.py",
        "return days, [float(sum(by_day[d], Decimal(0)) / len(by_day[d])) for d in days]",
    ): ("research summary metric", "exit-grid research note"),
    (
        "src/sextant/paper/alpaca_feed.py",
        "def _decimal(value: float | int | Decimal) -> Decimal:",
    ): (
        "vendor SDK numeric type, parsed through str() and never float arithmetic",
        "alpaca-py stream payload",
    ),
    (
        "src/sextant/paper/alpaca_feed.py",
        "def _quantity(value: float, label: str, *, lot_size: int = 1) -> Quantity:",
    ): ("vendor SDK numeric type, parsed through str()", "alpaca-py stream payload"),
    (
        "src/sextant/paper/alpaca_feed.py",
        "def _price(value: float, precision: int) -> Price:",
    ): ("vendor SDK numeric type, parsed through str()", "alpaca-py stream payload"),
    (
        "src/sextant/paper/b_protector.py",
        "trail_percent=float(self._parameters.native_trail_fraction * 100),",
    ): (
        "Decimal percent rendered only for the vendor request",
        "alpaca-py TrailingStopOrderRequest",
    ),
    (
        "src/sextant/backtest/thin_slice.py",
        "def calculate_from_realized_pnls(self, realized_pnls: list[float]) -> float | None:",
    ): ("Nautilus analyzer override signature", "nautechsystems/nautilus_trader analysis API"),
    (
        "src/sextant/backtest/thin_slice.py",
        "return float(len(realized_pnls))",
    ): (
        "Nautilus analyzer override return, a count not money",
        "nautechsystems/nautilus_trader analysis API",
    ),
    (
        "src/sextant/data/alpaca_history.py",
        "self.interval = float(Decimal(60) / calls_per_minute)",
    ): ("request pacing interval in seconds", "Alpaca market-data rate limit"),
    (
        "src/sextant/data/alpaca_history.py",
        "self.last: float | None = None",
    ): ("wall-clock pacing bookkeeping", "Alpaca market-data rate limit"),
    (
        "src/sextant/validation/trials.py",
        "objective: float | None = None,",
    ): ("optimization objective, a metric not money", "trial registry"),
}

FLOAT = re.compile(r"(?:\bfloat\s*\(|:\s*float\b|->\s*float\b|\|\s*float\b)")


def _sites() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if FLOAT.search(line) and not stripped.startswith("#"):
                found.append((relative, number, stripped))
    return found


def test_every_float_edge_is_named_and_sourced() -> None:
    unknown = [site for site in _sites() if (site[0], site[2]) not in ALLOWED]
    assert not unknown, "unnamed money/float edge(s): " + ", ".join(
        f"{path}:{number} {line!r}" for path, number, line in unknown
    )
    for key, (reason, source) in ALLOWED.items():
        assert reason and source, key


def test_alpaca_feed_parses_vendor_numbers_through_str() -> None:
    text = (SRC / "paper/alpaca_feed.py").read_text()
    assert "Decimal(str(value))" in text
    assert "Decimal(value)" not in text
    assert "_price(value: float" in text and "_quantity(value: float" in text


def test_trail_percent_is_decimal_until_the_sdk_call() -> None:
    text = (SRC / "paper/b_protector.py").read_text()
    assert "native_trail_fraction: Decimal" in text
    assert "native_trail_fraction * 100" in text
    assert "float(self._parameters.native_trail_fraction * 100)" in text
