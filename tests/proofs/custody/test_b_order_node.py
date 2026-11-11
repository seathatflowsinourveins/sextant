"""N3: the order-mode entry's own node (``build``/``run``, ``node.run()`` here) on the E5 fake
venue. Stand-ins: the data client and the execution client's venue (test_alpaca_node_owner.py's
wiring). The command's own shape is the default here: no ranking consumer, with the rank gate row
off (N3 part 3); a fixture consumer is passed only where named."""

from __future__ import annotations

import json
import threading
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.live.clients import (
    DataClientFactory,
    ExecutionClientFactory,
    MarketDataClient,
)
from nautilus_trader.model import (
    AccountBalance,
    AccountId,
    AccountType,
    Currency,
    Equity,
    InstrumentId,
    Money,
    OmsType,
    Price,
    Quantity,
    Venue,
)
from test_ranking import publisher
from test_ranking_consumer import consumer

from sextant.alpaca.execution import AlpacaExecutionClient
from sextant.alpaca.factories import AlpacaExecutionClientFactory
from sextant.alpaca.wire import AccountGateway
from sextant.execution.custody import AccountScope, CustodyError, WriterLease
from sextant.execution.pacer import AccountPacer
from sextant.paper import node_order
from sextant.paper.b_protector_main import EXPECTED_FULL_ENV, EXPECTED_SUFFIX_ENV
from sextant.ranking.registry import RANK_GATE_ENABLED
from sextant.tradingview.producer import SCOPE as MARKET

from .alpaca_venue import Venue as FakeVenue
from .conftest import controls
from .test_alpaca_node_claims import _filled, _holding
from .test_alpaca_node_owner import _owner

ROOT = Path(__file__).resolve().parents[3]
TIMING = dict(timeout_connection_secs=10, timeout_reconciliation_secs=10)
TIMING |= dict(timeout_portfolio_secs=5, timeout_disconnection_secs=2, delay_post_stop_secs=0)
SCOPE = AccountScope("ALPACA", "FIXTUREACCOUNT")
NUMBER = "PAFIXTURE0001"  # a fixture account number


def names(count: int) -> list[str]:
    out = []
    for index in range(count):
        word, index = "", index + 1
        while index:
            index, rest = divmod(index - 1, 26)
            word = chr(65 + rest) + word
        out.append("Z" + word)
    return out


def artifact(path: Path, symbols: list[str]) -> Path:
    """The ranked universe file in the K2 artifact's shape (baseline_recipe.load_universe)."""
    path.write_text(json.dumps({"rows": [{"symbol": name} for name in symbols]}))
    return path


class AccountVenue(FakeVenue):
    """The E5 fake plus GET /account, the read the old writer checks (b_protector_main)."""

    def get(self, path, params):
        if path == "/account":
            self.requests.append(("GET", path, params))
            return {"account_number": NUMBER, "equity": "100", "buying_power": "100"}
        return super().get(path, params)


@pytest.fixture(autouse=True)
def expected(monkeypatch):
    monkeypatch.setenv(EXPECTED_FULL_ENV, NUMBER)
    monkeypatch.delenv(EXPECTED_SUFFIX_ENV, raising=False)


def argv(tmp_path: Path, *, count: int = 3, slot: str = "2", **paths: Path) -> list[str]:
    account = tmp_path / "account.json"
    namespace = paths.pop("namespace", "BTEST")
    fields = dict(lane="alpaca-paper-b", account_id="FIXTUREACCOUNT", client_id="ALPACA")
    account.write_text(json.dumps(fields | {"namespace": str(namespace), "sessions": ["rth"]}))
    lanes = ROOT / "lanes"
    values = {
        "--account-config": account,
        "--universe-artifact": artifact(tmp_path / "universe.json", names(count)),
        "--b-parameters": paths.get("b", lanes / "paper/b-parameters.json"),
        "--entry-parameters": lanes / "paper/b-entry-parameters.json",
        "--exit-parameters": lanes / "paper/b-gain-lock.params.json",
        "--reentry-parameters": lanes / "paper/b-reentry-parameters.json",
        "--node-parameters": lanes / "paper/shared-node.params.json",
        "--custody-parameters": lanes / "custody-parameters.json",
        "--receipt-dir": tmp_path / "receipts",
        "--duration-s": paths.get("duration", "2"),
        "--api-key-env": "FIXTURE_KEY_NAME",
        "--api-secret-env": "FIXTURE_SECRET_NAME",
        "--paper-slot": slot,
        "--lease-root": tmp_path / "locks",
        "--existing-streams": "0",
        "--lease-source": "fixture: no stream exists",
    }
    return [str(part) for flag, value in values.items() for part in (flag, value)]


def equity(iid: InstrumentId) -> Equity:
    return Equity(
        instrument_id=iid,
        raw_symbol=iid.symbol,
        currency=Currency.from_str("USD"),
        price_precision=4,
        price_increment=Price.from_str("0.0001"),
        lot_size=Quantity.from_str("1"),
        ts_event=0,
        ts_init=0,
    )


class Stand:
    """The two stand-in factories and what they saw."""

    def __init__(self, venue: FakeVenue) -> None:
        self.venue, self.subscribed, self.connected = venue, 0, 0
        stand = self

        class Data(MarketDataClient):
            async def _connect(self):
                for iid in self.config.instrument_provider.load_ids or ():
                    self._handle_instrument(equity(InstrumentId.from_str(iid)))

            async def _disconnect(self):
                pass

            async def _subscribe_trades(self, command):
                stand.subscribed += len(command.instrument_ids)

            async def _subscribe_quotes(self, command):
                pass

            async def _subscribe_bars(self, command):
                pass

            async def _subscribe(self, command):
                pass

        class Exec(AlpacaExecutionClient):  # test_alpaca_node_owner.py's wiring
            async def _connect(self):
                stand.connected += 1
                self.gateway = AccountGateway(
                    venue, AccountPacer(controls(), self.clock.timestamp_ns), self._position_counts
                )
                self.commission_for_fill = lambda _data: Money.from_str("0 USD")
                balance = AccountBalance(
                    Money.from_str("100 USD"), Money.from_str("0 USD"), Money.from_str("100 USD")
                )
                self.generate_account_state([balance], [], True, self.clock.timestamp_ns())

        class DataFactory(DataClientFactory):
            @staticmethod
            def create(**kwargs):
                return Data(**kwargs, venue=Venue("ALPACA"))

        class ExecFactory(AlpacaExecutionClientFactory):
            @staticmethod
            def create(**kwargs):  # type: ignore[override]
                return Exec(
                    **kwargs,
                    venue=Venue("ALPACA"),
                    account_id=AccountId("ALPACA-BTEST"),
                    account_type=AccountType.MARGIN,
                    oms_type=OmsType.NETTING,
                )

        self.data, self.exec = DataFactory, ExecFactory


def start(
    tmp_path, venue=None, *, count=3, exec_factory=None, leases=None, with_consumer=False, **kw
):
    """Parse, then run the entry's own node on this thread; (receipt body, code, stand)."""
    # A publisher, when used, comes before the node: its MessageBus must not replace the node's.
    ranked = consumer(publisher()) if with_consumer else None
    stand = Stand(venue or AccountVenue())
    args = node_order.parse(argv(tmp_path, count=count, **kw))
    receipt, code = node_order.run(
        args,
        consumer=ranked,
        leases=leases or node_order.take_leases,
        data_factory=stand.data,
        exec_factory=exec_factory or stand.exec,
        timing=TIMING,
    )
    return json.loads(receipt.read_text()), code, stand


def writes(venue: FakeVenue) -> list[Any]:
    return [r for r in venue.requests if r[0] != "GET"]


@pytest.mark.parametrize("slot", ["1", "3"])
def test_slots_one_and_three_are_refused_before_anything(tmp_path, slot) -> None:
    with pytest.raises(node_order.OrderModeRefused, match="paper_slot"):
        node_order.parse(argv(tmp_path, slot=slot))
    assert node_order.main(argv(tmp_path, slot=slot)) == 2
    assert not (tmp_path / "locks").exists() and not (tmp_path / "receipts").exists()


def test_rows_protection_needs_only_the_native_row_and_the_rest_are_named_off(tmp_path) -> None:
    rows = node_order.parse(argv(tmp_path)).rows
    assert rows.native > 0 and rows.inflight_ms == 0
    assert rows.steps["protect"].startswith("on:")
    assert rows.width is None and "not streamed" in rows.steps["tighten"]  # 5-minute rows today
    for step in ("entry", "gain_lock", "reentry"):
        assert rows.steps[step].startswith("off:"), rows.steps[step]
    assert "chase_cap_fraction" in rows.steps["entry"]
    broken = [r for r in json.loads((ROOT / "lanes/paper/b-parameters.json").read_text())]
    broken = [r for r in broken if r["name"] != "native_trail_fraction"]
    (tmp_path / "b.json").write_text(json.dumps(broken))
    with pytest.raises(node_order.OrderModeRefused, match="registries"):
        node_order.parse(argv(tmp_path, b=tmp_path / "b.json"))


def test_with_the_rank_gate_off_the_command_needs_no_consumer(tmp_path) -> None:
    # P2 (b_lifecycle.py BLifecycleConfig): no consumer while the gate row is off. The held
    # lease stops the real command before any client could connect.
    old = WriterLease(SCOPE, tmp_path / "locks", "b-protector")
    old.acquire()
    try:
        assert node_order.main(argv(tmp_path)) == 2
    finally:
        old.close()
    body = json.loads((tmp_path / "receipts" / node_order.RECEIPT).read_text())
    assert (body["phase"], body["reason"]) == ("refused", "writer_lease")
    assert body["engine"]["cache_database"] is None and "not recovered" in body["restart"]


@pytest.mark.parametrize("value", [True, 0])  # only the bool False is off; 0 == False is not
def test_a_gate_row_that_is_on_still_needs_the_consumer(tmp_path, monkeypatch, value) -> None:
    monkeypatch.setattr(node_order, "RANK_GATE_ENABLED", replace(RANK_GATE_ENABLED, value=value))
    body, code, stand = start(tmp_path)
    assert (code, body["reason"]) == (2, "ranking_consumer") and stand.connected == 0
    assert not (tmp_path / "locks").exists()


def test_protection_only_starts_with_no_consumer_on_a_flat_account(tmp_path) -> None:
    venue = AccountVenue()
    body, code, stand = start(tmp_path, venue)
    assert (code, body["phase"], body["reason"]) == (0, "stopped", None)
    assert stand.subscribed == 3 and not writes(venue)  # the Strategy's own on_start ran
    assert body["steps"]["protect"].startswith("on:")
    entry = body["steps"]["entry"]  # the Strategy's own missing list, with the consumer named
    assert entry.startswith("off: the Strategy refuses entries") and "ranking_consumer" in entry


def test_a_held_writer_lease_refuses_and_nothing_connects(tmp_path) -> None:
    old = WriterLease(SCOPE, tmp_path / "locks", "b-protector")  # the old writer's own scope
    old.acquire()
    try:
        body, code, stand = start(tmp_path)
    finally:
        old.close()
    assert (code, body["reason"]) == (2, "writer_lease") and stand.connected == 0


def test_an_execution_client_other_than_the_paper_one_is_refused(tmp_path) -> None:
    class Other(ExecutionClientFactory):
        @staticmethod
        def create(**kwargs):
            raise AssertionError("never built")

    body, code, stand = start(tmp_path, exec_factory=Other)
    assert (code, body["reason"]) == (2, "execution_client") and stand.connected == 0
    free(tmp_path, SCOPE)  # the refusal released the lease


def test_an_old_writer_prefix_that_overlaps_the_house_prefix_is_refused(tmp_path) -> None:
    body, code, _ = start(tmp_path, namespace="O")
    assert (code, body["reason"]) == (2, "house_prefix")


def test_a_claim_list_over_one_startup_flush_is_refused_before_connect(tmp_path) -> None:
    body, code, stand = start(tmp_path, count=node_order.QUEUE + 1)
    assert (code, body["reason"]) == (2, "claim_list") and stand.connected == 0
    assert "1025 names" in body["detail"]


def test_a_flat_account_starts_the_strategy_and_a_stop_releases_the_lease(tmp_path, capfd) -> None:
    venue = AccountVenue()
    body, code, stand = start(tmp_path, venue, count=node_order.QUEUE, with_consumer=True)
    out = capfd.readouterr()
    assert (code, body["phase"], body["reason"]) == (0, "stopped", None)
    assert body["gate"] == {"open_positions": 0, "open_house_orders": 0, "withheld_holdings": 0}
    assert stand.subscribed == node_order.QUEUE  # the Strategy's own on_start ran
    assert body["claims"]["count"] == node_order.QUEUE
    assert "ranking_consumer" not in body["steps"]["entry"]  # the fixture consumer was passed
    assert "command queue is full" not in out.out + out.err  # LEAD-0336: a full queue fails
    assert not writes(venue)
    free(tmp_path, SCOPE)
    free(tmp_path, MARKET)


def free(tmp_path: Path, scope: AccountScope) -> None:
    lease = WriterLease(scope, tmp_path / "locks", "after")
    lease.acquire()  # raises CustodyError while any holder remains
    lease.close()


@pytest.mark.parametrize("case", ["holding", "house_order", "outside"])
def test_a_non_flat_account_stops_before_any_command(tmp_path, case) -> None:
    venue = AccountVenue()
    if case == "holding":
        _filled(venue, "owner-filled", "9", "2026-11-10T15:00:00Z").update(symbol="ZA")
        _holding(venue, "ZA", "9")
    elif case == "house_order":
        _owner(venue, "BTEST-trail-ZA-1-1", symbol="ZA", side="sell")
    else:
        _holding(venue, "OTHER", "5")
    seeded = len(venue.requests)
    body, code, stand = start(tmp_path, venue)
    reason = {"holding": "not_flat", "house_order": "house_order_open"}
    assert (code, body["phase"]) == (2, "refused")
    assert body["reason"] == reason.get(case, "holding_outside_claims")
    assert stand.subscribed == 0 and body["refused_sends"] == 0
    assert all(r[0] == "GET" for r in venue.requests[seeded:]), "nothing was sent"


def test_the_unchunked_flush_at_the_directory_size_logs_a_full_queue_and_fails(tmp_path, capfd):
    """The engine fact at LEAD-0336's 5,200, built past the refusal: the flush overflows the
    execution client's queue and shutdown_on_error aborts before the Strategy runs."""
    pub = publisher()
    stand = Stand(AccountVenue())
    args = node_order.parse(argv(tmp_path, count=3))
    ids = tuple(InstrumentId.from_str(f"{name}.ALPACA") for name in names(5200))
    args = replace(args, universe=ids)
    node, strategy = node_order.build(
        args,
        consumer=consumer(pub),
        data_factory=stand.data,
        exec_factory=stand.exec,
        timing=TIMING,
    )
    timer = threading.Timer(20, node.handle().stop)  # bounds the run if the start succeeds
    try:
        timer.start()
        node.run()
    finally:
        timer.cancel()
        node.dispose()
    out = capfd.readouterr()
    text = out.out + out.err
    full = sum(
        "[ERROR]" in line and "instrument update failed" in line and "queue is full" in line
        for line in text.splitlines()
    )
    assert full == 5200 - node_order.QUEUE, full  # LEAD-0336 measured 4,176
    assert "Shutdown signal received during startup" in text
    assert not strategy.gate.checked and stand.subscribed == 0
    del node, strategy


def test_both_leases_are_held_for_the_run_and_a_second_holder_is_refused(tmp_path) -> None:
    args = node_order.parse(argv(tmp_path))
    with ExitStack() as held:
        node_order.take_leases(held, args)
        for scope in (SCOPE, MARKET):
            with pytest.raises(CustodyError):
                free(tmp_path, scope)
        with ExitStack() as second, pytest.raises(node_order.OrderModeRefused, match="writer"):
            node_order.take_leases(second, args)
    free(tmp_path, SCOPE)
    free(tmp_path, MARKET)


def test_an_account_other_than_the_expected_one_stops_before_any_command(
    tmp_path, monkeypatch, capfd
) -> None:
    monkeypatch.setenv(EXPECTED_FULL_ENV, "PAOTHER0002")
    venue = AccountVenue()
    body, code, stand = start(tmp_path, venue)
    out = capfd.readouterr()
    assert (code, body["phase"], body["reason"]) == (2, "refused", "account_mismatch")
    assert stand.subscribed == 0 and not writes(venue)
    assert ("GET", "/account", {}) in venue.requests  # the account it reached was read
    for text in (out.out + out.err, json.dumps(body)):  # neither number is printed or kept
        assert NUMBER not in text and "PAOTHER0002" not in text


def test_no_expected_account_refuses_before_any_lease(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(EXPECTED_FULL_ENV)
    body, code, stand = start(tmp_path)
    assert (code, body["reason"]) == (2, "account_mismatch") and stand.connected == 0
    assert not (tmp_path / "locks").exists()


def test_a_holding_outside_the_claims_while_running_is_paged_once_per_name(tmp_path, capfd) -> None:
    rows = json.loads((ROOT / "lanes/paper/b-parameters.json").read_text())
    for row in rows:  # a one-second poll for the proof; the committed row is the authority
        row["value"] = "1" if row["name"] == "reconcile_interval_s" else row["value"]
    (tmp_path / "b.json").write_text(json.dumps(rows))
    venue = AccountVenue()
    later = threading.Timer(0.5, lambda: [_holding(venue, s, "5") for s in ("OUTA", "OUTB")])
    later.start()
    body, code, _ = start(tmp_path, venue, b=tmp_path / "b.json", duration="4")
    later.cancel()
    err = capfd.readouterr().err.splitlines()
    lines = [line for line in err if "holding_outside_claims_running" in line]
    assert (code, body["phase"]) == (0, "stopped")
    assert body["outside_holdings_paged"] == 2
    assert sorted(line.rsplit(" ", 1)[1] for line in lines) == ["OUTA", "OUTB"]  # once per name
    assert not writes(venue)
