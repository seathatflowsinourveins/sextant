"""Row 9 mechanism witnesses; fixture qualification is not deployment authority."""

from __future__ import annotations

import importlib
from dataclasses import replace
from decimal import Decimal as D
from typing import Any

import pytest
from nautilus_trader.model import InstrumentId, Quantity

A = InstrumentId.from_str("AAA.SIM")
B = InstrumentId.from_str("BBB.SIM")
C = InstrumentId.from_str("CCC.SIM")
NS = 1_000_000_000


def api():
    try:
        return importlib.import_module("sextant.reentry.policy")
    except ModuleNotFoundError:
        pytest.fail("The sourced replay re-entry admission layer is missing")


class Ranking:
    generation_key = "g1"
    known_at = 5 * NS
    fresh = True

    def __init__(self, ranks=None):
        self.ranks = {A: 1, B: 2, C: 3} if ranks is None else ranks

    def rank_of(self, symbol):
        return next((rank for iid, rank in self.ranks.items() if iid.symbol.value == symbol), None)


def fixtures():
    p = api()
    params = p.Params(
        cooldown_seconds=D("2"),
        retry_rank_band=5,
        rotation_rank_band=10,
        reentry_min_confidence=D("0.6"),
        confidence_size_floor=D("0.25"),
        rotation_lift_margin_bps=D("10"),
        rotation_score_ratio=D("1.2"),
        whipsaw_stopouts_max=2,
    )
    receipt = p.FlatReceipt(A, D(0), ("entry", "stop", "replacement"), 5 * NS)
    sell = p.FastSellFacts(A, D("10"), D("9.99"), NS, receipt)
    campaign = p.CampaignState(
        campaign_id="fixture-campaign",
        origin_instrument_id=A,
        current_instrument_id=A,
        mode="paper_unbounded",
        original_qty=D(10),
        original_notional=D(100),
        original_risk=D(2),
        remaining_qty=D(10),
        remaining_notional=D(100),
        remaining_risk=D(2),
        charged_loss=D(0),
        charged_fees=D(0),
        evidence_complete=True,
        reentry_count=0,
        version=0,
    )
    return p, params, sell, campaign


class Entry:
    """External qualification fixture; production detector is deliberately absent."""

    def __init__(
        self, *, setup="RECLAIM", confidence: D | None = D("0.8"), available=(A,), labels=None
    ):
        self.setup, self.confidence, self.available = setup, confidence, available
        self.labels = (
            {"confirmation": "retest", "extension": "NOT_EXTENDED"} if labels is None else labels
        )

    def qualify(self, instrument_id, *, now_ns, generation_key, sell):
        if instrument_id not in self.available:
            return None
        p = api()
        return p.EnterIntent(
            instrument_id,
            now_ns,
            generation_key,
            self.setup,
            D("10.01"),
            D("0.11"),
            self.confidence,
            self.labels,
        )


class Sizer:
    def __init__(self):
        self.calls = []

    def size(self, intent, *, confidence_multiplier, campaign):
        self.calls.append((intent.instrument_id, intent.confidence, confidence_multiplier))
        return Quantity.from_int(1)


def decide(
    *,
    now=7 * NS,
    entry=None,
    ranks=None,
    lineage=("entry", "stop", "replacement"),
    receipt: Any = "fixture",
    lane="alpaca-paper-a",
    count=0,
    held=(),
    candidates=(A, B, C),
):
    p, params, sell, campaign = fixtures()
    if receipt != "fixture":
        sell = replace(sell, flat_receipt=receipt)
    campaign = replace(campaign, reentry_count=count)
    sizer = Sizer()
    controller = p.Reentry(params, entry=entry, sizer=sizer, lane=lane)
    result = controller.after_sell(
        now_ns=now,
        ranking=ranks or Ranking(),
        sell=sell,
        required_lineage=lineage,
        candidates=candidates,
        held=held,
        campaign=campaign,
        stopouts=0,
    )
    return result, sizer, controller


@pytest.mark.parametrize("offset,kind", [(-1, "WAIT"), (0, "REENTER"), (1, "REENTER")])
def test_cooldown_is_from_flat_receipt_at_exact_nanosecond(offset, kind):
    result, _, _ = decide(now=7 * NS + offset, entry=Entry())
    assert result.kind == kind
    if kind == "WAIT":
        assert result.reason == "cooldown"
    else:
        assert result.cooldown_started_ns == 5 * NS


def test_net_zero_with_nonterminal_replacement_and_unknown_receipt_wait():
    p, _, sell, _ = fixtures()
    partial = replace(sell.flat_receipt, terminal_order_ids=("entry", "stop"))
    for receipt in (None, partial):
        result, sizer, _ = decide(entry=Entry(), receipt=receipt)
        assert result.kind == "WAIT" and sizer.calls == []
    with pytest.raises(ValueError):
        p.FlatReceipt(A, D("0.01"), ("entry",), 5 * NS)
    result, _, _ = decide(entry=Entry(), lineage=None)
    assert result.kind == "WAIT"


def test_stale_future_or_ambiguous_ranking_waits_before_sizing():
    for field, value in (("fresh", False), ("known_at", 8 * NS), ("generation_key", "")):
        ranking = Ranking()
        setattr(ranking, field, value)
        result, sizer, _ = decide(entry=Entry(), ranks=ranking)
        assert result.kind == "WAIT" and sizer.calls == []
    result, _, _ = decide(entry=Entry(), candidates=(A, A))
    assert result.kind == "WAIT"


def test_missing_confidence_is_refused_before_sizing():
    result, sizer, _ = decide(entry=Entry(confidence=None))
    assert result.kind == "WAIT" and result.reason == "missing_confidence"
    assert sizer.calls == []


def test_same_symbol_precedes_rotation_and_sizes_once_with_confidence():
    result, sizer, _ = decide(entry=Entry(available=(A, B)))
    assert result.kind == "REENTER" and result.to_instrument_id == A
    assert sizer.calls == [(A, D("0.8"), D("0.85"))]
    assert result.executable is False


def test_flat_slot_rotation_uses_best_unheld_qualified_first_leg_without_lift():
    result, sizer, _ = decide(
        entry=Entry(setup="FIRST_LEG", confidence=None, available=(B, C)), held=(B,)
    )
    assert result.kind == "ROTATE" and result.to_instrument_id == C
    assert result.expected_lift is None and result.confidence is None
    assert sizer.calls == [(C, None, None)]


def test_first_print_and_unknown_extension_breakout_are_never_bought():
    for entry in (
        Entry(labels={"confirmation": "first_print"}),
        Entry(setup="BREAKOUT", labels={"extension": "UNKNOWN"}),
    ):
        result, sizer, _ = decide(entry=entry)
        assert result.kind == "WAIT" and sizer.calls == []


def test_absent_setup_provider_stays_unavailable_not_a_quote_based_fallback():
    result, sizer, _ = decide()
    assert result.kind == "WAIT" and result.reason == "entry_provider_unavailable"
    assert sizer.calls == []


def test_paper_count_is_journalled_but_never_a_retry_cap():
    result, _, controller = decide(entry=Entry(), count=1000)
    assert result.kind == "REENTER" and result.count == 1001
    assert controller.journal[-1]["count"] == 1001
    assert controller.journal[-1]["generation_key"] == "g1"


@pytest.mark.parametrize(
    "lane,mode", [("alpaca-live", "live_nonrenewing"), ("ibkr-paper", "paper_unbounded")]
)
def test_live_and_ibkr_never_activate_reentry(lane, mode):
    p, params, sell, campaign = fixtures()
    sizer = Sizer()
    result = p.Reentry(params, entry=Entry(), sizer=sizer, lane=lane).after_sell(
        now_ns=7 * NS,
        ranking=Ranking(),
        sell=sell,
        required_lineage=("entry", "stop", "replacement"),
        candidates=(A,),
        held=(),
        campaign=replace(campaign, mode=mode),
        stopouts=0,
    )
    assert result.kind == "WAIT" and sizer.calls == []


@pytest.mark.parametrize(
    "value,kind", [(None, "WAIT"), ("0.003", "WAIT"), ("0.003000000000000001", "HELD_ROTATION")]
)
def test_held_rotation_lift_is_pair_bound_and_strict(value, kind):
    p, params, _, campaign = fixtures()
    controller = p.Reentry(
        params, entry=Entry(setup="FIRST_LEG", available=(B,)), sizer=Sizer(), lane="alpaca-paper-a"
    )
    lift = p.Lift(A, B, "g1", None if value is None else D(value), D("0.01"), D("10"))
    result = controller.held_rotation(
        now_ns=7 * NS,
        ranking=Ranking(),
        campaign=campaign,
        held=(A,),
        weakest_id=A,
        weakest_score=D(1),
        target=B,
        target_score=D("1.2"),
        lift=lift,
    )
    assert result.kind == kind
    assert result.executable is False
    wrong_pair = replace(lift, from_instrument_id=C)
    assert (
        controller.held_rotation(
            now_ns=7 * NS,
            ranking=Ranking(),
            campaign=campaign,
            held=(A,),
            weakest_id=A,
            weakest_score=D(1),
            target=B,
            target_score=D("1.2"),
            lift=wrong_pair,
        ).kind
        == "WAIT"
    )


def test_campaign_originals_and_remaining_budgets_never_refill():
    _, _, _, campaign = fixtures()
    depleted = campaign.from_previous(
        remaining_qty=D(8), remaining_notional=D(80), remaining_risk=D(1), version=1
    )
    for changes in (
        {"remaining_qty": D(9)},
        {"original_notional": D(110)},
        {"remaining_notional": D(90)},
        {"remaining_risk": D(2)},
    ):
        with pytest.raises(ValueError):
            depleted.from_previous(**changes, version=2)


def test_generation_change_during_qualification_never_reaches_sizing():
    ranking = Ranking()

    class ChangedEntry(Entry):
        def qualify(self, *args, **kwargs):
            result = super().qualify(*args, **kwargs)
            ranking.generation_key = "g2"
            return result

    result, sizer, _ = decide(entry=ChangedEntry(), ranks=ranking)
    assert result.kind == "WAIT" and sizer.calls == []


def test_money_and_thresholds_reject_floats_and_nonfinite_values():
    _, params, sell, _ = fixtures()
    for value in (0.5, D("NaN"), D("Infinity"), D("-0.1"), D("1.01")):
        with pytest.raises(ValueError):
            replace(params, confidence_size_floor=value)
    with pytest.raises(ValueError):
        replace(sell, sell_price=10.0)
    with pytest.raises(ValueError):
        replace(params, retry_rank_band=True)


def test_whipsaw_consumes_custody_count_but_does_not_invent_a_reset_provider():
    p, params, sell, campaign = fixtures()
    controller = p.Reentry(
        params, entry=Entry(setup="BREAKOUT"), sizer=Sizer(), lane="alpaca-paper-a"
    )
    result = controller.after_sell(
        now_ns=7 * NS,
        ranking=Ranking(),
        sell=sell,
        required_lineage=("entry", "stop", "replacement"),
        candidates=(A,),
        held=(),
        campaign=campaign,
        stopouts=2,
    )
    assert result.kind == "WAIT" and result.reason == "whipsaw_needs_capped_reclaim"


def test_native_replay_drives_same_admission_without_any_order():
    try:
        replay = importlib.import_module("sextant.reentry.replay")
    except ModuleNotFoundError:
        pytest.fail("The native replay admission seam is not implemented")
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, RiskEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import AccountType, Currency, Money, OmsType, Price, QuoteTick, Venue
    from nautilus_trader.testkit.providers import TestInstrumentProvider

    p, params, sell, campaign = fixtures()
    # Native FX fixture reused from row 7 for the clock mechanism, not equity execution.
    instrument = TestInstrumentProvider.audusd_sim()
    iid = instrument.id
    sell = replace(
        sell, instrument_id=iid, flat_receipt=replace(sell.flat_receipt, instrument_id=iid)
    )
    campaign = replace(campaign, origin_instrument_id=iid, current_instrument_id=iid)
    controller = p.Reentry(
        params, entry=Entry(available=(iid,)), sizer=Sizer(), lane="alpaca-paper-a"
    )
    request = dict(
        ranking=Ranking({iid: 1}),
        sell=sell,
        required_lineage=("entry", "stop", "replacement"),
        candidates=(iid,),
        held=(),
        campaign=campaign,
        stopouts=0,
    )
    quotes = [
        QuoteTick(
            iid,
            Price.from_str("10.00"),
            Price.from_str("10.01"),
            Quantity.from_int(10),
            Quantity.from_int(10),
            ts,
            ts,
        )
        for ts in (7 * NS - 1, 7 * NS, 7 * NS + 1)
    ]
    engine = BacktestEngine(
        BacktestEngineConfig(risk_engine=RiskEngineConfig(bypass=False), bypass_logging=True)
    )
    engine.add_venue(
        Venue("SIM"),
        OmsType.NETTING,
        AccountType.MARGIN,
        starting_balances=[Money.from_str("1000 USD")],
        base_currency=Currency.from_str("USD"),
        fee_model=MakerTakerFeeModel(maker_rate=D(0), taker_rate=D(0)),
    )
    engine.add_instrument(instrument)
    engine.add_data(quotes)
    strategy = replay.ReentryReplay(
        replay.ReentryReplayConfig(
            instrument_id=iid, controller=controller, provide=lambda _tick: request
        )
    )
    engine.add_strategy(strategy)
    try:
        engine.run()
        assert [row.kind for row in strategy.decisions] == ["WAIT", "REENTER", "WAIT"]
        assert engine.cache.orders() == []
    finally:
        engine.dispose()


def test_one_flat_receipt_cannot_publish_two_entry_proposals():
    p, params, sell, campaign = fixtures()
    sizer = Sizer()
    controller = p.Reentry(params, entry=Entry(), sizer=sizer, lane="alpaca-paper-a")
    ranking = Ranking()
    request = dict(
        ranking=ranking,
        sell=sell,
        required_lineage=("entry", "stop", "replacement"),
        candidates=(A,),
        held=(),
        campaign=campaign,
        stopouts=0,
    )
    assert controller.after_sell(now_ns=7 * NS, **request).kind == "REENTER"
    ranking.generation_key = "g2"
    second = controller.after_sell(now_ns=7 * NS + 1, **request)
    assert second.kind == "WAIT" and len(sizer.calls) == 1


def test_contradictory_held_sold_symbol_and_unknown_setup_wait():
    result, sizer, _ = decide(entry=Entry(available=(A, B)), held=(A,))
    assert result.kind == "WAIT" and sizer.calls == []
    result, sizer, _ = decide(entry=Entry(setup="UNVERIFIED", available=(B,)))
    assert result.kind == "WAIT" and sizer.calls == []


def test_invalid_held_rotation_ranking_is_wait_not_an_exception():
    p, params, _, campaign = fixtures()

    class BrokenRanking(Ranking):
        def rank_of(self, symbol):
            raise ValueError("unavailable ranking")

    lift = p.Lift(A, B, "g1", D("0.004"), D("0.01"), D(10))
    result = p.Reentry(
        params, entry=Entry(available=(B,)), sizer=Sizer(), lane="replay"
    ).held_rotation(
        now_ns=7 * NS,
        ranking=BrokenRanking(),
        campaign=campaign,
        held=(A,),
        weakest_id=A,
        weakest_score=D(1),
        target=B,
        target_score=D(2),
        lift=lift,
    )
    assert result.kind == "WAIT"
