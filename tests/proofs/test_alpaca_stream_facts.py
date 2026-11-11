"""N1e part A: the stream-facts records and the ranking Actor's reader of them.

The data client that publishes these records arrives in part B; here the records are handed
to the Actor directly, as the client will publish them.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from alpaca.data.models import Trade
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from test_alpaca_data import INSTRUMENT_ID

from sextant.alpaca.stream_facts import AlpacaTradeFacts, StreamFacts, trade_facts
from sextant.ranking.node_actor import RankingActor, RankingActorConfig


@pytest.mark.parametrize(
    ("conditions", "expected"),
    [(["@", "I"], ("@", "I")), ([], ()), (None, None), ("@", None), (["@", 7], None)],
)
def test_conditions_are_kept_only_as_the_vendors_string_list(conditions, expected) -> None:
    raw = {"t": "2026-11-09T15:00:00Z", "p": 10.02, "s": 7, "x": "D", "i": 1, "z": "C"}
    if conditions is not None:
        raw["c"] = conditions
    tick = TradeTick(
        INSTRUMENT_ID,
        Price.from_str("10.02"),
        Quantity.from_int(7),
        AggressorSide.NO_AGGRESSOR,
        TradeId("D-1"),
        1,
        2,
    )
    try:
        trade = Trade("AAPL", raw)
    except Exception:  # the SDK model refuses a mixed list itself
        assert expected is None
        return
    assert trade_facts(trade, tick).conditions == expected


def test_the_actor_reads_facts_only_for_the_same_trade() -> None:
    source = StreamFacts("sip")
    other = InstrumentId.from_str("MSFT.ALPACA")

    def tick(trade_id: str, iid: InstrumentId = INSTRUMENT_ID) -> TradeTick:
        return TradeTick(
            iid,
            Price.from_str("10.02"),
            Quantity.from_int(7),
            AggressorSide.NO_AGGRESSOR,
            TradeId(trade_id),
            1,
            2,
        )

    assert source(tick("D-1")) is None  # nothing seen yet
    source.record(AlpacaTradeFacts(INSTRUMENT_ID, "D-1", ("@",), "C", 1, 2))
    assert source(tick("D-1")) == (True, ("@",))
    assert source(tick("D-2")) is None  # a different trade never borrows these facts
    assert source(tick("D-1", other)) is None
    source.record(AlpacaTradeFacts(INSTRUMENT_ID, "D-3", None, "C", 1, 2))
    assert source(tick("D-3")) is None  # unknown conditions are unknown facts
    assert source.facts_type.type_name == "AlpacaTradeFacts"
    assert source.gap_type.type_name == "AlpacaStreamGap"


def test_stream_facts_never_survive_an_actor_restart() -> None:  # review P2
    from nautilus_trader.model import CustomData
    from test_ranking_actor import IDS
    from test_ranking_actor import priming as primed
    from test_ranking_actor_evidence import Evidence, run_twice

    source, hosts = StreamFacts("sip"), []

    def build() -> Evidence:
        hosts.append(Evidence([]))
        return hosts[-1]

    class FirstRunFacts(RankingActor):
        starts = 0

        def on_start(self) -> None:
            self.starts += 1
            super().on_start()

        def on_trade(self, trade: TradeTick) -> None:
            if self.starts == 1:  # only the first run's client sends facts
                facts = AlpacaTradeFacts(
                    trade.instrument_id, trade.trade_id.value, ("@",), "C", 1, 2
                )
                self.on_data(CustomData(source.facts_type, facts))
            super().on_trade(trade)

    actor = FirstRunFacts(
        RankingActorConfig(
            instrument_ids=IDS,
            feed="sip",
            host_factory=cast(Any, build),
            priming=primed,
            page_window_s=3600,
            trade_facts=source,
        )
    )
    run_twice(actor)
    assert len(hosts) == 2 and actor.errors == {}
    penny = hosts[-1].publisher.assets["PENNY"]
    assert penny is not None and penny.halted is None  # no facts this run: nothing clears
