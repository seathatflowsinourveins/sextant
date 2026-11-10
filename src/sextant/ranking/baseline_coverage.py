"""Baseline coverage for arming: which symbols a loaded table really holds.

``BaselineTable.window`` correctly returns ``None`` for a missing slice (a
missing slice is not a zero), but arming must not spend a slot on a symbol whose
slice does not exist. These helpers read the table the arming call already
loaded; the coverage rule itself stays in ``build_baseline`` (explicit complete
coverage, linear within minute, first POST minute omitted).

The arming side names symbols as ``SYMBOL.ALPACA`` instrument ids, as
``paper/c_live_main.py`` builds them; the table keys are the bare vendor tickers.
"""

from collections.abc import Iterable

from sextant.ranking.baseline import BaselineTable

BASELINE_COVERED = "covered"
BASELINE_MISSING = "baseline_missing"
VENUE_SUFFIX = ".ALPACA"


def bare_symbol(symbol: str) -> str:
    """The vendor ticker an arming instrument id names; only the venue suffix is stripped.

    A ticker may itself carry dots (``BRK.B``), so this never splits at the
    first dot.
    """
    return symbol.removesuffix(VENUE_SUFFIX)


def partition_covered(
    baseline: BaselineTable, symbols: Iterable[str], segment: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split ``symbols`` into covered and missing, keeping the caller's order.

    The missing names are refused for arming; they never become a zero slice.
    """
    covered: list[str] = []
    missing: list[str] = []
    for symbol in symbols:
        target = covered if baseline.covers(bare_symbol(symbol), segment) else missing
        target.append(symbol)
    return tuple(covered), tuple(missing)


def coverage_receipt(
    baseline: BaselineTable, symbols: Iterable[str], segment: str
) -> dict[str, dict[str, object]]:
    """The per-symbol receipt field: coverage state, session count, latest session."""
    receipt: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        sessions = baseline.sessions(bare_symbol(symbol), segment)
        receipt[symbol] = {
            "segment": segment,
            "state": BASELINE_COVERED if sessions else BASELINE_MISSING,
            "sessions": len(sessions),
            "latest_session": sessions[-1] if sessions else None,
        }
    return receipt
