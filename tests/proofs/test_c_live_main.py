"""Proofs for the C live main: refusals, one writer, dry run, entry and trail.

No key, no network.  A fake trading client and a fake SIP feed replay the same
short surge the C session's own proofs use, so the production ``place`` seam,
the pacer, custody, guard, writer lease, receipt and trial row all run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, TrailingStopOrderRequest
from nautilus_trader.model import (
    AggressorSide,
    InstrumentId,
    Price,
    Quantity,
    QuoteTick,
    TradeId,
    TradeTick,
)

from sextant.execution.custody import AccountScope, WriterLease
from sextant.paper.c_live_main import _equity_ladder, main
from sextant.ranking.baseline import BaselineSample, BaselineTable, dump_baseline
from sextant.validation.trials import TrialLog

NS = 1_000_000_000
SEC = NS
START = 1_794_234_600 * SEC  # 2026-11-09T10:00 ET, the RTH open
ACCOUNT = "PA3C0000CU3B"
SUFFIX = "CU3B"
API_KEY = "test-api-key-3"
SECRET = "test-secret-3"  # noqa: S105
IID = InstrumentId.from_str("OMH.ALPACA")
D = Decimal


def write_config(tmp_path: Path, *, lane: str = "alpaca-paper-c") -> Path:
    path = tmp_path / "account.json"
    path.write_text(
        json.dumps(
            {
                "lane": lane,
                "account_id": "C001",
                "client_id": "c-live-proof",
                "namespace": "C001",
                "sessions": ["rth"],
            }
        )
    )
    return path


def write_baseline(tmp_path: Path) -> Path:
    table = BaselineTable(
        samples=(
            BaselineSample("OMH", "RTH", "2026-11-06", 0, D(0), D(0)),
            BaselineSample("OMH", "RTH", "2026-11-06", 600, D(600), D(60)),
        ),
        provenance="fixture explicit complete curve; linear within minute",
        known_at=START - SEC,
        feed="sip",
    )
    path = tmp_path / "baseline.json"
    path.write_text(dump_baseline(table))
    return path


@dataclass
class Clock:
    value: int = START

    def __call__(self) -> int:
        return self.value


@dataclass
class Monotonic:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class FakeTradingClient:
    def __init__(
        self,
        *,
        positions: tuple[Any, ...] = (),
        orders: tuple[Any, ...] = (),
        account_number: str = ACCOUNT,
        ack_status: str = "filled",
        poll_status: str = "filled",
    ) -> None:
        self.account = SimpleNamespace(account_number=account_number)
        self.positions = list(positions)
        self.orders = list(orders)
        self.ack_status = ack_status
        self.poll_status = poll_status
        self.calls: list[str] = []
        self.submitted: list[Any] = []
        self.polls = 0

    def get_account(self) -> Any:
        self.calls.append("get_account")
        return self.account

    def get_all_positions(self) -> Any:
        self.calls.append("get_all_positions")
        return self.positions

    def get_orders(self, filter: Any = None) -> Any:
        self.calls.append("get_orders")
        return self.orders

    def get_asset(self, symbol_or_asset_id: object) -> Any:
        self.calls.append("get_asset")
        return SimpleNamespace(price_increment=0.01)

    def submit_order(self, order_data: Any) -> Any:
        self.calls.append("submit_order")
        self.submitted.append(order_data)
        return SimpleNamespace(
            id=f"order-{len(self.submitted)}",
            client_order_id=order_data.client_order_id,
            status=self.ack_status,
            filled_qty=order_data.qty,
        )

    def get_order_by_id(self, order_id: object) -> Any:
        self.calls.append("get_order_by_id")
        self.polls += 1
        return SimpleNamespace(
            id=order_id,
            status=self.poll_status,
            filled_qty=D(1),
        )


def trade(seconds: int, price: str, size: int = 100) -> TradeTick:
    ts = START + seconds * SEC
    return TradeTick(
        IID,
        Price.from_str(price),
        Quantity.from_int(size),
        AggressorSide.NO_AGGRESSOR,
        TradeId(f"OMH-{ts}"),
        ts,
        ts,
    )


def quote(seconds: int, bid: str, ask: str) -> QuoteTick:
    ts = START + seconds * SEC
    return QuoteTick(
        IID,
        Price.from_str(bid),
        Price.from_str(ask),
        Quantity.from_int(100),
        Quantity.from_int(100),
        ts,
        ts,
    )


def replay(feed: FakeFeed) -> None:
    """The C session's warm-up, flag, first leg and ask quote, with the live clock."""

    for seconds, price, size in (
        (0, "1.0000", 100),
        (25, "1.0100", 100),
        (26, "1.0100", 100),
        (30, "1.0000", 100),
        (31, "1.0300", 500),
        (32, "1.0400", 500),
    ):
        feed.clock.value = START + seconds * SEC
        feed.on_trade(trade(seconds, price, size))
    feed.clock.value = START + 32 * SEC
    feed.on_quote(quote(32, "1.0400", "1.0600"))
    feed.clock.value = START + 33 * SEC
    feed.on_trade(trade(33, "1.0500", 500))
    for seconds in range(34, 39):
        feed.clock.value = START + seconds * SEC
        feed.on_trade(trade(seconds, "1.0200", 100))
    feed.clock.value = START + 38 * SEC
    feed.on_quote(quote(38, "1.0200", "1.0300"))


class FakeFeed:
    def __init__(
        self,
        instruments: Any,
        *,
        on_trade: Any,
        on_quote: Any,
        api_key: str,
        secret_key: str,
        feed: str,
        clock: Clock,
        replay: Any,
    ) -> None:
        self.instruments = instruments
        self.on_trade = on_trade
        self.on_quote = on_quote
        self.api_key = api_key
        self.secret_key = secret_key
        self.feed = feed
        self.clock = clock
        self.replay = replay
        self.failure: Exception | None = None
        self.stopped = False

    def start(self) -> None:
        self.replay(self)

    def stop(self) -> None:
        self.stopped = True


def invoke(
    tmp_path: Path,
    client: FakeTradingClient,
    clock: Clock,
    mono: Monotonic,
    *,
    dry_run: bool = False,
    ledger: Path | None = None,
) -> int:
    def feed_factory(instruments: Any, **kwargs: Any) -> FakeFeed:
        return FakeFeed(instruments, clock=clock, replay=replay, **kwargs)

    def sleep(seconds: float) -> None:
        mono.sleep(seconds)
        clock.value += int(seconds * SEC)

    argv = [
        "--config",
        str(write_config(tmp_path)),
        "--symbols",
        "OMH.ALPACA",
        "--baseline",
        str(write_baseline(tmp_path)),
        "--state",
        str(tmp_path / "state"),
        "--seconds",
        "1",
    ]
    if dry_run:
        argv.append("--dry-run")
    return main(
        argv,
        client_factory=lambda **_: client,
        feed_factory=feed_factory,
        now_ns=clock,
        sleep=sleep,
        monotonic=mono,
        ledger_path=ledger if ledger is not None else tmp_path / "trials.parquet",
    )


@pytest.fixture
def live_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("ALPACA_PAPER_3_API_KEY", API_KEY)
    monkeypatch.setenv("ALPACA_PAPER_3_SECRET_KEY", SECRET)
    monkeypatch.setenv("C_EXPECTED_ACCOUNT_SUFFIX", SUFFIX)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def receipt(tmp_path: Path) -> dict[str, Any]:
    paths = list((tmp_path / "reports/paper-c").glob("*/session.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text())


def test_a_missing_asset_price_increment_falls_back_to_the_n4_ladder() -> None:
    precision, increment = _equity_ladder(SimpleNamespace(price_increment=None))
    assert (precision, increment) == (4, D("0.0001"))


def test_an_asset_price_increment_keeps_its_precision() -> None:
    precision, increment = _equity_ladder(SimpleNamespace(price_increment=0.01))
    assert (precision, increment) == (2, D("0.01"))


def test_suffix_mismatch_refuses_before_any_order(
    live_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("C_EXPECTED_ACCOUNT_SUFFIX", "ZZZZ")
    client = FakeTradingClient()
    with pytest.raises(SystemExit) as refusal:
        invoke(live_env, client, Clock(), Monotonic())
    assert refusal.value.code != 0
    assert client.submitted == []
    assert "submit_order" not in client.calls


def test_an_open_position_refuses_before_any_order(live_env: Path) -> None:
    client = FakeTradingClient(positions=(SimpleNamespace(symbol="OMH"),))
    with pytest.raises(SystemExit) as refusal:
        invoke(live_env, client, Clock(), Monotonic())
    assert refusal.value.code != 0
    assert client.submitted == []
    assert "get_orders" not in client.calls


def test_an_open_order_refuses_before_any_order(live_env: Path) -> None:
    client = FakeTradingClient(orders=(SimpleNamespace(id="other-order"),))
    with pytest.raises(SystemExit) as refusal:
        invoke(live_env, client, Clock(), Monotonic())
    assert refusal.value.code != 0
    assert client.submitted == []
    assert "get_asset" not in client.calls


def test_a_second_writer_cannot_acquire_the_lease(live_env: Path) -> None:
    root = live_env / "state" / "writer.lock"
    lease = WriterLease(AccountScope("ALPACA", ACCOUNT), root, "other-writer")
    lease.acquire()
    client = FakeTradingClient()
    try:
        with pytest.raises(SystemExit) as refusal:
            invoke(live_env, client, Clock(), Monotonic())
    finally:
        lease.close()
    assert refusal.value.code != 0
    assert client.submitted == []


def test_dry_run_prints_the_command_and_sends_nothing(live_env: Path) -> None:
    client = FakeTradingClient()
    assert invoke(live_env, client, Clock(), Monotonic(), dry_run=True) == 0

    assert client.submitted == []
    assert "submit_order" not in client.calls
    written = receipt(live_env)
    assert written["dry_run"] is True
    assert written["tier"] == "BROKER-PAPER"
    assert [row["status"] for row in written["commands"]] == ["DRY_RUN"]
    assert written["protection_cid"] is None


def test_the_entry_is_a_limit_buy_and_the_fill_rests_a_gtc_trailing_sell(
    live_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeTradingClient()
    assert invoke(live_env, client, Clock(), Monotonic()) == 0

    buy, trail = client.submitted
    assert isinstance(buy, LimitOrderRequest)
    assert buy.side is OrderSide.BUY
    assert buy.time_in_force is TimeInForce.DAY
    assert buy.extended_hours is False
    assert D(str(buy.limit_price)) == D("1.03")
    assert D(str(buy.qty)) == D("1")

    assert isinstance(trail, TrailingStopOrderRequest)
    assert trail.side is OrderSide.SELL
    assert trail.time_in_force is TimeInForce.GTC
    assert trail.symbol == "OMH"
    assert D(str(trail.qty)) == D("1")
    assert D(str(trail.trail_percent)) == D("2.5")

    written = receipt(live_env)
    assert written["tier"] == "BROKER-PAPER"
    assert written["account_suffix"] == SUFFIX
    assert written["symbols"] == ["OMH.ALPACA"]
    assert written["dry_run"] is False
    assert [row["kind"] for row in written["commands"]] == ["LIMIT", "TRAILING_STOP"]
    assert [row["side"] for row in written["commands"]] == ["BUY", "SELL"]
    assert written["commands"][0]["status"] == "FILLED"
    assert written["commands"][0]["fill"] == "1"
    assert written["commands"][1]["trail"] == "2.5"
    assert written["commands"][1]["status"] == "FILLED"
    assert written["protection_cid"] == trail.client_order_id
    assert written["entry_params_hash"]
    assert written["baseline"]["feed"] == "sip"

    captured = capsys.readouterr()
    assert API_KEY not in captured.out + captured.err
    assert SECRET not in captured.out + captured.err
    assert ACCOUNT not in captured.out + captured.err


def test_an_unknown_order_state_stops_without_a_resubmit(live_env: Path) -> None:
    client = FakeTradingClient(ack_status="new", poll_status="new")
    assert invoke(live_env, client, Clock(), Monotonic()) == 1

    assert len(client.submitted) == 1
    assert client.polls > 0
    written = receipt(live_env)
    assert written["commands"][0]["status"] == "SUBMITTED"
    assert written["commands"][0]["fill"] == "0"
    assert any("state unknown" in error for error in written["errors"])

    rows = TrialLog(live_env / "trials.parquet").records
    assert len(rows) == 1
    assert rows[0]["state"] == "FAIL"
    params = json.loads(rows[0]["params"])
    assert params["errors"]
    assert params["entries"] == 1
    assert params["fills"] == 0


def test_the_trial_row_records_the_run_identity_and_outcome(live_env: Path) -> None:
    client = FakeTradingClient()
    assert invoke(live_env, client, Clock(), Monotonic()) == 0

    rows = TrialLog(live_env / "trials.parquet").records
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "COMPLETE"
    config = json.loads(row["config"])
    assert config["tier"] == "BROKER-PAPER"
    assert len(config["implementation_sha"]) == 40
    int(config["implementation_sha"], 16)
    params = json.loads(row["params"])
    assert params["flags"] == 1
    assert params["entries"] == 1
    assert params["fills"] == 2
    assert params["protection_cid"].endswith("-trail")
    assert "pnl" not in json.dumps(params).lower()
