"""Lead 2026-11-08: exact method compatibility, no relabeling or wildcard."""

from copy import deepcopy

import pytest
from test_display_lists import AS_OF, DIGEST, NOW, focus, row, snapshot

from sextant.ranking.publisher import METHOD
from sextant.tradingview.display_lists import build_display_lists

MOVER = "MOVER-v2@00203275944a22655b3e14b221cfde9a265d549a"


@pytest.mark.parametrize("method", ["potential/2", MOVER])
def test_exact_authorized_methods_keep_source_method_and_members(method):
    source = snapshot([row("AAA", 1)])
    source["weights_version"] = source["symbols"][0]["weights_version"] = method
    before = deepcopy(source)
    doc = build_display_lists(
        source,
        focus("AAA"),
        snapshot_path="s.json",
        snapshot_sha256=DIGEST,
        generated_at=NOW.isoformat(),
    )
    assert doc["ns_movers"] == [
        {"symbol": "AAA", "tradingview_symbol": "NASDAQ:AAA", "labels": ["early:1"]}
    ]
    assert source == before
    assert METHOD == MOVER  # Pin the publisher string, per the lead's exact-allowlist ruling.


@pytest.mark.parametrize("where", ["snapshot", "row"])
@pytest.mark.parametrize(
    "method", ["potential/3", "MOVER-v2", MOVER + "-new", "MOVER-v2@other", None]
)
def test_other_method_labels_never_pass_either_guard(where, method):
    source = snapshot([row("AAA", 1)])
    target = source if where == "snapshot" else source["symbols"][0]
    target["weights_version"] = method
    with pytest.raises(ValueError):
        build_display_lists(
            source,
            focus("AAA"),
            snapshot_path="s.json",
            snapshot_sha256=DIGEST,
            generated_at=NOW.isoformat(),
        )
    assert source["as_of"] == AS_OF


@pytest.mark.parametrize(
    "symbol,mapping,expected",
    [
        ("AAA.ALPACA", {"AAA": "NASDAQ:AAA"}, ("NASDAQ:AAA", "symbol_map")),
        ("AAA.XNAS", {}, ("NASDAQ:AAA", "scanner_exchange")),
        ("BRK.B.NYSE", {}, ("NASDAQ:BRK.B", "scanner_exchange")),
        ("BRK.B", {}, ("NASDAQ:BRK.B", "scanner_exchange")),
        ("IBKR", {}, ("NASDAQ:IBKR", "scanner_exchange")),
        ("aaa", {}, (None, "UNVERIFIED")),
    ],
)
def test_listing_qualification_strips_only_known_engine_suffixes(symbol, mapping, expected):
    from sextant.tradingview.display_support import qualify_tradingview_symbol

    assert qualify_tradingview_symbol(symbol, {"exchange": "NASDAQ"}, mapping) == expected


@pytest.mark.parametrize("symbol", [" AAA", "AAA ", ""])
def test_listing_qualification_refuses_whitespace_instead_of_inventing_a_ticker(symbol):
    from sextant.tradingview.display_support import qualify_tradingview_symbol

    with pytest.raises(ValueError):
        qualify_tradingview_symbol(symbol, {"exchange": "NASDAQ"})


def test_display_phase_refuses_an_unzoned_clock():
    from datetime import datetime

    from sextant.tradingview.display_support import phase

    with pytest.raises(ValueError):
        phase(datetime(2026, 11, 8, 20))
