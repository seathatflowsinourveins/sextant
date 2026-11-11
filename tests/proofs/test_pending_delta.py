from dataclasses import replace
from decimal import Decimal

import pytest
from nautilus_trader.execution import StaticLatencyModel
from nautilus_trader.model import OrderSide
from test_b_lifecycle import GATE_ON, NS, PENNY, quote
from test_b_lifecycle_entry import QUOTES, at, run_entry
from test_b_lifecycle_protect import NATIVE, Owner, trails
from test_b_lifecycle_protect import OPEN
import test_b_lifecycle_width as width_proofs


@pytest.mark.parametrize(
    "actions",
    [
        (("1.5", "BUY", 50),),
        (("1.5", "SELL", 20),),
        (("1.5", "BUY", 50), ("2.0", "SELL", 20)),
        (("1.5", "BUY", 50), ("2.0", "BUY", 10), ("2.5", "SELL", 10)),
        (("1.5", "SELL", 20), ("2.0", "BUY", 20)),
    ],
)
def test_other_fills_do_not_answer_a_modify_before_it_reaches_the_venue(tmp_path, actions):
    delay = 3 * NS

    class Observe(Owner):
        def __init__(self, config):
            super().__init__(config)
            self.wire = []
            self.early_answers = []
            self.updates = []
            self.gaps = []

        def modify_order(
            self,
            client_order_id,
            quantity=None,
            price=None,
            trigger_price=None,
            client_id=None,
            params=None,
        ):
            self.wire.append(
                (self.clock.timestamp_ns(), client_order_id, quantity, self._held(self.books[PENNY]))
            )
            super().modify_order(client_order_id, quantity, price, trigger_price, client_id, params)

        def on_order_updated(self, event):
            book = self.books[PENNY]
            client_order_id = event.client_order_id
            sent_at = book.sent_at.get(client_order_id)
            asked = book.asked.get(client_order_id)
            self.updates.append(
                (event.ts_event - at("0"), str(client_order_id), str(event.quantity),
                 str(self._held(book)), asked, sent_at)
            )
            super().on_order_updated(event)
            if sent_at is not None and event.ts_event < sent_at + delay:
                if client_order_id not in book.pending:
                    self.early_answers.append(self.updates[-1])

        def on_quote(self, event):
            super().on_quote(event)
            book = self.books[PENNY]
            orders = self.cache.orders(instrument_id=PENNY, strategy_id=self.strategy_id)
            house = [order for order in trails(orders) if not order.is_closed]
            reserved = sum(
                (order.leaves_qty.as_decimal() for order in orders
                 if not order.is_closed and order.side is OrderSide.SELL
                 and not self._house(order.client_order_id)),
                Decimal(0),
            )
            coverage = sum((order.leaves_qty.as_decimal() for order in house), Decimal(0))
            needed = self._held(book) - reserved
            if book.pending and coverage < needed:
                self.gaps.append((event.ts_event - at("0"), str(coverage), str(needed)))

    Observe.actions = (
        (at("0.7"), "OWNER-INITIAL", OrderSide.BUY, 100, "0.6000"),
        *(
            (at(seconds), f"OWNER-{index}", getattr(OrderSide, side), amount,
             "0.6000" if side == "BUY" else "0.4000")
            for index, (seconds, side, amount) in enumerate(actions)
        ),
    )
    journal, orders, strategy = run_entry(
        tmp_path,
        cls=Observe,
        gate=replace(GATE_ON, value=False),
        native_trail_fraction=NATIVE,
        quotes=[*QUOTES, *(quote(at(str(step / 10)), "0.5200", "0.5250")
                            for step in range(8, 101))],
        latency=StaticLatencyModel(update_latency_nanos=delay),
    )
    print("ACTIONS", actions)
    print("WIRE", [(stamp - at("0"), str(client_order_id), str(quantity), str(held))
                   for stamp, client_order_id, quantity, held in strategy.wire])
    print("UPDATES", strategy.updates)
    print("EARLY", strategy.early_answers)
    print("GAPS", strategy.gaps)
    print("PAGES", [row for row in journal if row["kind"] == "page"])
    assert not strategy.early_answers
    assert not strategy.gaps


@pytest.mark.parametrize("delayed", [False, True])
def test_an_added_fill_gets_its_own_protection_while_an_offset_modify_waits(tmp_path, delayed):
    added_at = OPEN + 3 * width_proofs.MINUTE + NS // 4

    class ObserveAdded(Owner):
        actions = (
            (at("0.7"), "OWNER-INITIAL", OrderSide.BUY, 100, "0.6000"),
            (added_at, "OWNER-ADDED", OrderSide.BUY, 50, "0.6000"),
        )

        def __init__(self, config):
            super().__init__(config)
            self.at_fill = []

        def on_order_filled(self, event):
            super().on_order_filled(event)
            if str(event.client_order_id) == "OWNER-ADDED":
                book = self.books[PENNY]
                orders = self.cache.orders(instrument_id=PENNY, strategy_id=self.strategy_id)
                live = [order for order in trails(orders) if not order.is_closed]
                self.at_fill.append(
                    dict(
                        held=self._held(book),
                        coverage=sum((order.leaves_qty.as_decimal() for order in live), Decimal(0)),
                        trails=[(str(order.client_order_id), order.status.name,
                                 str(order.quantity), order.ts_init) for order in live],
                        pending=dict(book.pending),
                    )
                )

    journal, orders, strategy = run_entry(
        tmp_path,
        cls=ObserveAdded,
        gate=replace(GATE_ON, value=False),
        native_trail_fraction=NATIVE,
        width_rows=dict(width_proofs.ROWS),
        quotes=[*QUOTES, *width_proofs.rth_quotes()],
        bars=width_proofs.bars(),
        extra_trades=width_proofs.rth_tape(),
        latency=StaticLatencyModel(update_latency_nanos=3 * width_proofs.MINUTE if delayed else 0),
    )
    print("DELAYED", delayed, "AT FILL", strategy.at_fill)
    protects = [row for row in journal if row["kind"] == "protect"]
    print("PROTECTS", protects)
    assert strategy.at_fill
    assert all(row["coverage"] >= row["held"] for row in strategy.at_fill)
    assert any(row["ts"] == added_at and row["quantity"] == "50" for row in protects)
