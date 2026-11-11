"""N1f fix round (Codex xhigh r1 at 44b860fe, P1): an amendment names its print in full.

The first proof is the reviewer's witness (review-gpt-gates/n1frows-44b860f-codex-r1,
test_delta_witnesses.py:37-54) unchanged. The lead's ruling (04:2x): the identity is exchange,
original id, original price and original size; an id match with another price or size is not
the stored print, withdraws nothing and is counted as its own receipt class.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
import test_ranking_amendments as amendments
from nautilus_trader.model import CustomData


@pytest.mark.parametrize(
    ("field", "value"),
    [("original_price", Decimal("9.99")), ("original_size", Decimal("999"))],
)
def test_an_amendment_must_match_the_original_price_and_size(tmp_path, monkeypatch, field, value):
    make_amendment = amendments.amendment

    def mismatched(kind, symbol, original_id, now):
        event = make_amendment(kind, symbol, original_id, now)
        return CustomData(event.data_type, replace(event.data, **{field: value}))

    monkeypatch.setattr(amendments, "amendment", mismatched)
    result = amendments.amended_run(tmp_path, (365, "correction", "PENNY", 60))
    actual_rank = amendments.rank(result, 420)
    assert actual_rank is not None, (
        f"D-60 was price=0.50, size=100; nonmatching {field}={value} "
        f"incorrectly withdrew its rank: {actual_rank}"
    )


def test_a_mismatched_amendment_is_its_own_receipt_class(tmp_path, monkeypatch) -> None:
    make_amendment = amendments.amendment

    def mismatched(kind, symbol, original_id, now):
        event = make_amendment(kind, symbol, original_id, now)
        return CustomData(event.data_type, replace(event.data, original_price=Decimal("9.99")))

    monkeypatch.setattr(amendments, "amendment", mismatched)
    amendments.amended_run(tmp_path, (365, "correction", "PENNY", 60))
    receipt = amendments.receipt(tmp_path)
    assert receipt["amendments"] == {"inside": 0, "outside": 0, "unprimed": 0}
    assert receipt["amendments_mismatched"] == {"count": 1, "notional": "999.00"}
