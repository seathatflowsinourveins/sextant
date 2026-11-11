"""N1d (LEAD-0020 2b, 2e): a name's halt state starts unknown and moves only on evidence.

A real BacktestNode replays fixture PENNY prints at 0, 60, ... 360 s and fixture statuses.
"Not halted" needs a price-eligible print received after the status subscription is active
with no halt since; only a resume clears a halt; a stream gap resets every name.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from nautilus_trader.common import SocketState, SocketStateChanged
from nautilus_trader.core import UUID4
from nautilus_trader.model import ClientId, MarketStatusAction, TraderId
from test_ranking import NS, START
from test_ranking_actor import IDS, ROOT, FakeHost, Logged, equity, priming, run
from test_ranking_actor_status import OTHER, status

from sextant.ranking.engine import EXCLUDED_CONDITIONS
from sextant.ranking.node_actor import RankingActorConfig

HALT, TRADING = MarketStatusAction.HALT, MarketStatusAction.TRADING


def regular(_tick) -> tuple[bool, tuple[str, ...]]:
    return True, ()  # fixture: a price-eligible print with no condition


class Evidence(FakeHost):
    """Records each set_symbol after priming: name, halted and the asset's known time (s)."""

    def __init__(self, log, fail_at=None) -> None:
        super().__init__(log, fail_at)
        self.assets: list[tuple[str, bool | None, int]] = []

    def set_symbol(self, name, *, references, asset) -> Any:
        self.assets.append((name, asset.halted, (asset.known_at - START) // NS))
        return super().set_symbol(name, references=references, asset=asset)


def moves(out) -> list[tuple[str, bool | None, int]]:
    return out["hosts"][0].assets[3:]  # the first three are the primed universe


def test_every_name_starts_unknown_whatever_priming_says(tmp_path) -> None:
    out = run(tmp_path, host_cls=Evidence)  # priming says halted False; no eligibility source
    primed = out["hosts"][0].assets[:3]
    assert [halted for _, halted, _ in primed] == [None, None, None]
    assert moves(out) == []  # with no source of eligibility no print clears
    assert out["actor"].evidence() == dict(
        unknown=3, not_halted=0, halted=0, cleared_by_print=0, resets=0
    )


def test_the_actor_reads_the_producers_own_mask() -> None:
    producer = (ROOT / "src/sextant/tradingview/producer.py").read_text()
    assert 'excluded = bool({"G", "U", "Z", "6", "M", "9"}.intersection(conditions))' in producer
    assert {"G", "U", "Z", "6", "M", "9"} == EXCLUDED_CONDITIONS


def test_the_first_eligible_print_clears_and_later_prints_change_nothing(tmp_path) -> None:
    out = run(tmp_path, host_cls=Evidence, facts=regular)
    assert moves(out) == [("PENNY", False, 0)]
    assert out["actor"].evidence() == dict(
        unknown=2, not_halted=1, halted=0, cleared_by_print=1, resets=0
    )


@pytest.mark.parametrize(
    "facts",
    [
        lambda _t: (True, ("Z",)),  # out-of-sequence report: the producer's mask
        lambda _t: (True, ("6",)),  # closing print: the engine's mask
        lambda _t: (False, ()),  # the vendor's own price mask
        lambda _t: None,  # facts unknown for this print
    ],
)
def test_a_masked_or_unknown_print_never_clears(tmp_path, facts) -> None:
    out = run(tmp_path, host_cls=Evidence, facts=facts)
    assert moves(out) == [] and out["actor"].evidence()["unknown"] == 3


def test_a_failing_fact_source_is_counted_and_the_feed_continues(tmp_path) -> None:
    def broken(_tick):
        raise RuntimeError("fixture fact source failure")

    out = run(tmp_path, host_cls=Evidence, facts=broken)
    assert moves(out) == [] and out["actor"].errors == {"trade_facts": 12}
    assert out["hosts"][0].calls == 12  # every print still reached the host


def test_a_print_during_a_halt_does_not_clear_and_only_a_resume_does(tmp_path) -> None:
    feed = [
        status(30, HALT),
        status(45, MarketStatusAction.NONE),  # unclassified: still halted
        status(200, TRADING, is_trading=True),
    ]
    out = run(tmp_path, host_cls=Evidence, facts=regular, statuses=feed)
    assert moves(out) == [("PENNY", False, 0), ("PENNY", True, 30), ("PENNY", False, 200)]
    held = run(tmp_path / "held", host_cls=Evidence, facts=regular, statuses=feed[:2])
    assert moves(held) == [("PENNY", False, 0), ("PENNY", True, 30)]  # prints 60-360 ignored
    assert held["actor"].evidence()["halted"] == 1


def test_a_print_before_the_status_subscription_is_active_does_not_clear(tmp_path) -> None:
    class Late(Logged):
        def watch_statuses(self) -> None:  # the subscription becomes active at 200 s
            self.clock.set_time_alert_ns(
                "late", START + 200 * NS, lambda _e: super(Late, self).watch_statuses()
            )

    out = run(tmp_path, host_cls=Evidence, facts=regular, actor_cls=Late)
    assert moves(out) == [("PENNY", False, 240)]  # prints 0-180 preceded it


def gap(actor, at_s: int, state=SocketState.DISCONNECTED) -> None:
    def fire(_event) -> None:
        now = actor.clock.timestamp_ns()
        actor.on_socket_state(  # the engine's own handler, as the live node delivers it
            SocketStateChanged(
                TraderId.from_str("TRADER-001"),
                ClientId("ALPACA"),
                None,
                "stream",
                state,
                UUID4(),
                now,
                now,
            )
        )

    actor.clock.set_time_alert_ns(f"gap-{at_s}", START + at_s * NS, fire)


def test_a_stream_gap_resets_every_name_and_the_rule_applies_again(tmp_path) -> None:
    subscribed: list[str] = []

    class Gapped(Logged):
        def subscribe_socket_state(self, client_id=None, endpoint=None, priority=None) -> None:
            subscribed.append("socket")
            super().subscribe_socket_state(client_id, endpoint, priority)

        def watch_statuses(self) -> None:
            super().watch_statuses()
            gap(self, 200)
            gap(self, 270, SocketState.CONNECTED)

    out = run(tmp_path, host_cls=Evidence, facts=regular, actor_cls=Gapped)
    assert subscribed == ["socket"]
    assert moves(out) == [
        ("PENNY", False, 0),
        ("PENNY", None, 200),
        ("PENNY", False, 240),
        ("PENNY", None, 270),
        ("PENNY", False, 300),
    ]
    assert out["actor"].evidence() == dict(
        unknown=2, not_halted=1, halted=0, cleared_by_print=3, resets=2
    )


def test_the_node_entry_can_reset_when_the_client_reports_no_socket_state(tmp_path) -> None:
    class Entry(Logged):
        def watch_statuses(self) -> None:
            super().watch_statuses()
            self.clock.set_time_alert_ns(
                "reset", START + 200 * NS, lambda _e: self.reset_evidence()
            )

    out = run(tmp_path, host_cls=Evidence, facts=regular, actor_cls=Entry)
    assert moves(out) == [("PENNY", False, 0), ("PENNY", None, 200), ("PENNY", False, 240)]
    assert out["actor"].evidence()["resets"] == 1


def test_a_name_outside_the_universe_is_ignored(tmp_path) -> None:
    class Wider(Logged):
        def watch_statuses(self) -> None:
            super().watch_statuses()
            self.subscribe_instrument_status(OTHER)

    feed = [status(30, HALT, iid=OTHER)]
    out = run(
        tmp_path,
        host_cls=Evidence,
        facts=regular,
        statuses=feed,
        actor_cls=Wider,
        extra=[equity(OTHER)],
    )
    assert moves(out) == [("PENNY", False, 0)] and out["actor"].ignored_statuses == 1
    assert (
        sum(
            v
            for k, v in out["actor"].evidence().items()
            if k in {"unknown", "not_halted", "halted"}
        )
        == 3
    )


def test_the_subscribe_recorder_is_off_by_default_and_counts_first_statuses_in_window(
    tmp_path,
) -> None:
    feed = [
        status(30, HALT),  # PENNY's first status, inside 60 s of subscribing
        status(50, TRADING, is_trading=True),  # a change after one: not counted
        status(90, TRADING, iid=IDS[0], is_trading=True),  # ADR's first, outside the window
    ]
    off = run(tmp_path, host_cls=Evidence, facts=regular, statuses=feed)
    assert off["actor"].snapshot_statuses is None
    on = run(tmp_path / "on", host_cls=Evidence, facts=regular, statuses=feed, snapshot_window=60)
    assert on["actor"].snapshot_statuses == {"HALT": 1}


def test_new_config_keys_are_required_bounded_and_misspellings_refused() -> None:
    base: dict[str, Any] = dict(
        instrument_ids=IDS,
        feed="sip",
        host_factory=cast(Any, lambda: FakeHost([])),
        priming=priming,
        page_window_s=3600,
    )
    with pytest.raises(TypeError, match="trade_facts"):  # no default eligibility source
        RankingActorConfig(**base)
    with pytest.raises(TypeError, match=r"'trade_fact'"):
        RankingActorConfig(**base, trade_facts=None, trade_fact=regular)
    for bad in (0, -5, 1.5, True):
        with pytest.raises(ValueError, match="status_snapshot_window_s"):
            RankingActorConfig(**base, trade_facts=None, status_snapshot_window_s=cast(Any, bad))
    with pytest.raises(ValueError, match="trade_facts"):
        RankingActorConfig(**base, trade_facts=cast(Any, "regular"))
    assert RankingActorConfig(**base, trade_facts=regular).status_snapshot_window_s is None


def test_statuses_before_priming_fold_by_the_same_rule(tmp_path) -> None:  # review F1 in N1d
    class Early(Logged):
        def on_start(self) -> None:
            original = self._priming

            def prime():
                self.on_instrument_status(status(-2, HALT))
                self.on_instrument_status(status(-1, MarketStatusAction.NONE))  # no resume
                return original()

            self._priming = prime
            super().on_start()

    out = run(tmp_path, host_cls=Evidence, facts=regular, actor_cls=Early)
    assert moves(out)[0] == ("PENNY", True, -1)  # still halted: only a resume clears it
    assert out["actor"].evidence()["halted"] == 1  # prints 0-360 never cleared it


def test_a_clear_the_host_refuses_leaves_the_name_unknown(tmp_path) -> None:  # review F2 in N1d
    class RefusesClears(Evidence):
        def set_symbol(self, name, *, references, asset):
            if name == "PENNY" and asset.halted is False:
                raise RuntimeError("fixture setter unavailable")
            return super().set_symbol(name, references=references, asset=asset)

    out = run(tmp_path, host_cls=RefusesClears, facts=regular)
    assert out["actor"].evidence()["not_halted"] == 0 and out["actor"].errors["set_symbol"] >= 1
    assert all(halted is None for _, halted, _ in out["hosts"][0].assets)
