# pyright: reportIncompatibleMethodOverride=false
from __future__ import annotations

import json
import socket
from dataclasses import replace
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest
import test_ranking_amendments as amendments
from alpaca.data.models import Trade
from nautilus_trader.model import CustomData, DataType
from test_alpaca_data import INSTRUMENT_ID, TRADE
from test_ranking import NS, START
from test_ranking_actor import FakeHost, Logged, run
from test_ranking_node_main import argv as capacity_argv
from test_ranking_node_ranking import argv as ranking_argv
from test_ranking_node_rollover import two_segments
from test_ranking_node_session import Regular

from sextant.alpaca import data, stream_facts
from sextant.ranking import node_actor, node_main, node_parameters, node_ranking


@pytest.fixture(autouse=True)
def no_external_connection(monkeypatch):
    def refuse(*arguments, **keywords):
        raise AssertionError("Offline review: network connection refused")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


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


# Adapted at the fix (lead ruling 04:2x): bucket_window_s has no row any more, which
# test_an_override_cannot_hide_a_missing_row below covers unchanged.
@pytest.mark.parametrize("name", ["status_snapshot_window_s"])
def test_an_unavailable_row_cannot_gain_authority_from_a_bare_flag(name):
    rows = node_parameters.load()
    assert rows[name].status == "UNAVAILABLE" and rows[name].value is None
    with pytest.raises(ValueError, match=name):
        node_parameters.resolve(rows, name, 600)


def test_an_override_cannot_hide_a_missing_row():
    with pytest.raises((KeyError, ValueError), match="bucket_window_s"):
        node_parameters.resolve({}, "bucket_window_s", 600)


# Adapted at the fix: the fixture no longer passes the retired flag, so the witness passes it.
def test_capacity_entry_refuses_an_unsourced_bucket_window(tmp_path):
    with pytest.raises(ValueError, match="bucket_window_s"):
        node_main.parse([*capacity_argv(tmp_path), "--bucket-window-s", "60"])


# Adapted at the fix: the fixture no longer passes the retired flag, so the witness passes it.
def test_ranking_entry_refuses_an_unsourced_snapshot_window(tmp_path):
    with pytest.raises(ValueError, match="status_snapshot_window_s"):
        node_ranking.parse([*ranking_argv(tmp_path), "--status-snapshot-window-s", "60"])


@pytest.mark.parametrize("field", ["unit", "last_change"])
def test_replacement_registries_require_each_rows_metadata(tmp_path, field):
    registry = json.loads(node_parameters.DEFAULT_PATH.read_text())
    del registry["rows"]["page_window_s"][field]
    path = tmp_path / "parameters.json"
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="page_window_s"):
        node_parameters.load(path)


def test_capacity_registry_is_not_the_monitors_export_interval():
    root = Path(node_main.__file__).resolve().parents[3]
    monitor = json.loads((root / "deploy/monitor/systemd/parameters.json").read_text())
    row = next(item for item in monitor["rows"] if item["name"] == "monitor_bridge_period_seconds")
    assert row["value"] == 60
    assert row["applies_to"] == "sextant-monitor.timer OnStartupSec and OnUnitActiveSec"
    registry = node_parameters.load()
    assert registry["receipt_interval_s"].value == row["value"]
    assert "capacity" not in (root / "scripts/monitor_l3_l4.py").read_text()
    assert "capacity" not in (root / "scripts/monitor_evidence.py").read_text()


@pytest.mark.parametrize("original_id", [60, int("7" * 40)])
def test_tick_and_amendment_use_the_identical_vendor_id_rule(original_id):
    assert data.vendor_trade_id is node_actor.vendor_trade_id is stream_facts.vendor_trade_id
    stock = data._Stock(INSTRUMENT_ID, INSTRUMENT_ID.symbol.value, 2, 0)
    row = Trade(stock.symbol, {**TRADE, "i": original_id})
    tick = data._trade_tick(row, stock)
    event = amendments.amendment("correction", "AAPL", original_id, START).data
    assert tick.trade_id.value == node_actor.vendor_trade_id(event.exchange, event.original_id)
    assert len(tick.trade_id.value) <= 36


def test_an_unrelated_facts_source_does_not_route_amendments(tmp_path, monkeypatch):
    session_run = amendments.session_run
    monkeypatch.setattr(
        amendments, "session_run", partial(session_run, facts=lambda tick: (True, ("@",)))
    )
    result = amendments.amended_run(tmp_path, (365, "correction", "PENNY", 60))
    assert amendments.rank(result, 420) is not None
    assert amendments.receipt(tmp_path)["amendments"] == {"inside": 0, "outside": 0, "unprimed": 0}
    assert "amendment" not in result["actor"].errors


def test_a_host_without_the_optional_amendment_method_ignores_updates(tmp_path):
    assert not hasattr(FakeHost, "on_amendment")

    class Amending(Logged):
        def watch_statuses(self):
            super().watch_statuses()

            def deliver(event):
                self.on_data(amendments.amendment("cancel", "PENNY", 60, self.clock.timestamp_ns()))

            self.clock.set_time_alert_ns("optional-host-amendment", START + 365 * NS, deliver)

    result = run(tmp_path, actor_cls=Amending, facts=Regular("sip"), trades=amendments.trades())
    assert "amendment" not in result["actor"].errors
    assert amendments.rank(result, 420) is not None


def test_no_pending_amendment_can_publish_a_score_or_a_rank(tmp_path):
    result = amendments.amended_run(
        tmp_path, (365, "correction", "PENNY", 60), (370, "cancel", "PENNY", 120)
    )
    withheld = [
        generation
        for generation in result["receiver"].received
        if START + 365 * NS <= generation.known_at <= START + 540 * NS
    ]
    assert withheld
    for generation in withheld:
        row = next(row for row in generation.rows if row.symbol == "PENNY")
        assert row.rank is None and row.score is None
    assert amendments.rank(result, 600) is not None
    assert result["session"].host.amended == {}


def test_an_old_segments_amendment_cannot_taint_the_new_segment(tmp_path, monkeypatch):
    first, second = two_segments(361)
    session_run = amendments.session_run
    monkeypatch.setattr(
        amendments,
        "session_run",
        partial(
            session_run, segments=lambda timestamp: first if timestamp < first.end_ns else second
        ),
    )
    result = amendments.amended_run(
        tmp_path, (355, "correction", "PENNY", 60), (365, "cancel", "PENNY", 60)
    )
    before = amendments.receipt(tmp_path)
    after = json.loads((tmp_path / "receipts/ranking-2026-10-27-RTH.json").read_text())
    assert before["amendments"] == {"inside": 1, "outside": 0, "unprimed": 0}
    assert after["amendments"] == {"inside": 0, "outside": 1, "unprimed": 0}
    assert result["session"].host.amended == {}


def test_error_action_uses_the_same_cancel_withdrawal_rule(tmp_path, monkeypatch):
    make_amendment = amendments.amendment

    def error_cancel(kind, symbol, original_id, now):
        event = make_amendment(kind, symbol, original_id, now)
        return CustomData(event.data_type, replace(event.data, action="E"))

    monkeypatch.setattr(amendments, "amendment", error_cancel)
    result = amendments.amended_run(tmp_path, (365, "cancel", "PENNY", 60))
    assert amendments.rank(result, 365) is None
    assert amendments.rank(result, 540) is not None
    assert amendments.receipt(tmp_path)["amendments"]["inside"] == 1


@pytest.mark.parametrize("stream_source", [True, False])
def test_both_amendment_subscriptions_exist_only_for_stream_facts(tmp_path, stream_source):
    subscriptions = []

    class Subscriptions(Logged):
        def subscribe_data(self, *arguments, **keywords):
            subscriptions.append(arguments[0])
            return super().subscribe_data(*arguments, **keywords)

    source = Regular("sip") if stream_source else lambda tick: (True, ("@",))
    amendments.session_run(tmp_path, actor_cls=Subscriptions, facts=source)
    observed = [item for item in subscriptions if item.type_name in stream_facts.AMENDMENTS]
    expected = [DataType(kind, metadata={"feed": "sip"}) for kind in stream_facts.AMENDMENTS]
    assert observed == (expected if stream_source else [])


@pytest.mark.parametrize("before_tick", [True, False])
def test_a_tick_cannot_republish_an_amended_name_in_either_callback_order(tmp_path, before_tick):
    class Racing(Logged):
        def on_trade(self, tick):
            affected = (
                str(tick.instrument_id.symbol) == "PENNY" and tick.ts_event == START + 420 * NS
            )
            event = amendments.amendment("correction", "PENNY", 60, self.clock.timestamp_ns())
            if affected and before_tick:
                self.on_data(event)
            super().on_trade(tick)
            if affected and not before_tick:
                self.on_data(event)

    result = amendments.session_run(tmp_path, actor_cls=Racing, trades=amendments.trades())
    same_turn = [
        generation
        for generation in result["receiver"].received
        if generation.known_at == START + 420 * NS
    ]
    row = next(row for row in same_turn[-1].rows if row.symbol == "PENNY")
    assert row.rank is None and row.score is None
    assert amendments.rank(result, 480) is None
    assert amendments.rank(result, 540) is not None
