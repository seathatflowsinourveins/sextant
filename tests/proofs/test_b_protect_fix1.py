# pyright: reportAttributeAccessIssue=false
"""S1 fix round 1: the protection core's three review findings, each witnessed first.

1. A cancel rejection that arrives after its retry is already due still leaves a retry on the
   engine's clock (review s1p2-de481ca), so a quiet feed cannot leave the trail unretried.
Fixture values only; the stand-in is test_b_protect_single's.
"""

from __future__ import annotations

from test_b_lifecycle import PENNY
from test_b_protect_cancel import CID, cancels, fire, mismatched, rejected

from sextant.exits.engine import CANCEL_RETRY_NS


def test_an_overdue_cancel_rejection_retries_on_the_clock_in_a_quiet_feed():
    engine = mismatched()
    book = engine.books[PENNY]
    engine.now += CANCEL_RETRY_NS + 1  # the rejection arrives after its retry is due
    rejected(engine)
    assert len(cancels(engine)) == 1, "re-sent inside the rejection's callback"
    assert CID in book.recancel and engine.alerts, "no retry on the clock"
    fire(engine, engine.now + CANCEL_RETRY_NS)  # no quote, trade or order event
    assert len(cancels(engine)) == 2
