"""Proofs for the C live main: refusals, one writer, dry run, entry and trail.

No key, no network.  A fake trading client and a fake tick feed replay the same
short surge the C session's own proofs use, so the production ``place`` seam,
the pacer, custody, guard, writer lease, receipt and trial row all run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from alpaca.common.utils import validate_uuid_id_param
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

import sextant.paper.c_live_main as c_live_main_module
from sextant.execution.alpaca import OrderCommand
from sextant.execution.custody import (
    AccountScope,
    AccountSnapshot,
    Custody,
    OrderFact,
    PositionAuthority,
    WriterLease,
)
from sextant.paper.c_live_main import (
    _arm_universe,
    _equity_ladder,
    _house_cid,
    _request_for,
    main,
)
from sextant.paper.config import PaperAccount
from sextant.paper.feed_tap import FeedTap
from sextant.paper.sessions import Session
from sextant.ranking.baseline import (
    BaselineSample,
    BaselineTable,
    dump_baseline,
    segment_start,
)
from sextant.validation.trials import TrialLog, snapshot_hash

NS = 1_000_000_000
SEC = NS
MIN = 60 * SEC
HOUR = 3_600 * SEC
START = 1_794_234_600 * SEC  # 2026-11-09T09:30 ET, the RTH open
OVERNIGHT_CLOCK = START + 10 * HOUR + 30 * MIN + 10 * SEC  # 2026-11-09T20:00:10 ET
PRE_SWITCH_CLOCK = START - 5 * HOUR - 30 * MIN - 10 * SEC  # 2026-11-09T03:59:50 ET
POST_CLOCK = START + 6 * HOUR + 30 * MIN + 10 * SEC  # 2026-11-09T16:00:10 ET
ACCOUNT = "PA3C0000CU3B"
SUFFIX = "CU3B"
API_KEY = "test-api-key-3"
SECRET = "test-secret-3"  # noqa: S105
IID = InstrumentId.from_str("OMH.ALPACA")
DDD_IID = InstrumentId.from_str("DDD.ALPACA")
PRE_OPEN_CLOCK = PRE_SWITCH_CLOCK + 20 * SEC
RTH_AFTER_OPEN = START + 10 * SEC
ET = ZoneInfo("America/New_York")
D = Decimal


def write_config(
    tmp_path: Path, *, lane: str = "alpaca-paper-c", account_id: str = ACCOUNT
) -> Path:
    path = tmp_path / "account.json"
    path.write_text(
        json.dumps(
            {
                "lane": lane,
                "account_id": account_id,
                "client_id": "c-live-proof",
                "namespace": "C001",
                "sessions": ["rth"],
            }
        )
    )
    return path


def write_baseline(
    tmp_path: Path,
    *,
    segment: str = "RTH",
    feed: str = "sip",
    provenance: str = "fixture explicit complete curve; linear within minute",
    name: str = "baseline.json",
    symbols: tuple[str, ...] = ("OMH",),
) -> Path:
    samples = tuple(
        sample
        for symbol in symbols
        for sample in (
            BaselineSample(symbol, segment, "2026-11-06", 0, D(0), D(0)),
            BaselineSample(symbol, segment, "2026-11-06", 600, D(600), D(60)),
        )
    )
    table = BaselineTable(
        samples=samples,
        provenance=provenance,
        known_at=START - 8 * HOUR,
        feed=feed,
    )
    path = tmp_path / name
    path.write_text(dump_baseline(table))
    return path


def write_baseline_dir(
    tmp_path: Path,
    *,
    segments: tuple[str, ...] = ("OVERNIGHT", "PRE", "RTH", "POST"),
    symbols: tuple[str, ...] = ("OMH",),
) -> Path:
    directory = tmp_path / "baselines"
    directory.mkdir()
    for segment in segments:
        write_baseline(
            directory,
            segment=segment,
            feed="boats" if segment == "OVERNIGHT" else "sip",
            provenance=f"{segment.lower()} baseline",
            name=f"{segment.lower()}.json",
            symbols=symbols,
        )
    return directory


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
        assets: tuple[Any, ...] = (),
        account_number: str = ACCOUNT,
        ack_status: str = "filled",
        poll_status: str = "filled",
        tradable: bool = True,
        overnight_tradable: bool = True,
        overnight_halted: bool = False,
        exit_ack_status: str = "new",
        trail_ack_status: str | None = None,
        validate_order_ids: bool = False,
    ) -> None:
        self.account = SimpleNamespace(
            account_number=account_number, equity="10000", buying_power="10000"
        )
        self.positions = list(positions)
        self.orders = list(orders)
        self.assets = list(assets)
        self.ack_status = ack_status
        self.poll_status = poll_status
        self.tradable = tradable
        self.overnight_tradable = overnight_tradable
        self.overnight_halted = overnight_halted
        self.exit_ack_status = exit_ack_status
        self.trail_ack_status = ack_status if trail_ack_status is None else trail_ack_status
        self.validate_order_ids = validate_order_ids
        self.calls: list[str] = []
        self.submitted: list[Any] = []
        self.polls = 0
        self.client_polls: list[str] = []
        self.orders_by_id: dict[str, Any] = {}
        self.orders_by_cid: dict[str, tuple[Any, str]] = {}
        self.overrides: dict[str, str] = {}
        self.cancelled: list[str] = []
        self.replaced: list[tuple[str, Any]] = []
        self.fail_account_reads = False

    def get_account(self) -> Any:
        self.calls.append("get_account")
        if self.fail_account_reads:
            raise RuntimeError("the account read is unavailable")
        return self.account

    def get_all_positions(self) -> Any:
        self.calls.append("get_all_positions")
        return self.positions

    def get_orders(self, filter: Any = None) -> Any:
        self.calls.append("get_orders")
        return self.orders

    def get_all_assets(self, filter: Any = None) -> Any:
        self.calls.append("get_all_assets")
        return self.assets

    def get_asset(self, symbol_or_asset_id: object) -> Any:
        self.calls.append("get_asset")
        wanted = getattr(symbol_or_asset_id, "value", symbol_or_asset_id)
        for row in self.assets:
            if getattr(row, "symbol", None) == str(wanted):
                return row
        return SimpleNamespace(
            price_increment=0.01,
            tradable=self.tradable,
            overnight_tradable=self.overnight_tradable,
            overnight_halted=self.overnight_halted,
        )

    def submit_order(self, order_data: Any) -> Any:
        self.calls.append("submit_order")
        self.submitted.append(order_data)
        order_id = f"order-{len(self.submitted)}"
        status = "new"
        filled_qty: Any = 0
        filled_avg_price: str | None = None
        if isinstance(order_data, LimitOrderRequest) and order_data.side is OrderSide.BUY:
            status = self.ack_status
            filled_qty = order_data.qty
            filled_avg_price = "1.05"
        elif isinstance(order_data, TrailingStopOrderRequest):
            status = self.trail_ack_status
            filled_qty = order_data.qty
        elif isinstance(order_data, LimitOrderRequest) and order_data.side is OrderSide.SELL:
            status = self.exit_ack_status
        self.orders_by_id[order_id] = order_data
        self.orders_by_cid[str(order_data.client_order_id)] = (order_data, order_id)
        return SimpleNamespace(
            id=order_id,
            client_order_id=order_data.client_order_id,
            status=status,
            filled_qty=D(str(filled_qty)),
            filled_avg_price=filled_avg_price,
        )

    def get_order_by_id(self, order_id: object) -> Any:
        self.calls.append("get_order_by_id")
        if self.validate_order_ids:
            validate_uuid_id_param(str(order_id), "order_id")
        self.polls += 1
        key = str(order_id)
        request = self.orders_by_id.get(key)
        status = self.overrides.get(key, self.poll_status)
        filled_qty = D(1)
        filled_avg_price: str | None = None
        if isinstance(request, LimitOrderRequest) and request.side is OrderSide.BUY:
            filled_avg_price = "1.05"
        elif isinstance(request, LimitOrderRequest):
            filled_qty = D(0)
        return SimpleNamespace(
            id=order_id,
            status=status,
            filled_qty=filled_qty,
            filled_avg_price=filled_avg_price,
        )

    def get_order_by_client_id(self, client_id: str) -> Any:
        self.calls.append("get_order_by_client_id")
        self.client_polls.append(client_id)
        request, order_id = self.orders_by_cid[client_id]
        status = self.overrides.get(client_id, self.poll_status)
        filled = status.upper() == "FILLED"
        requested = D(str(getattr(request, "qty", 0)))
        filled_qty: Any = requested if filled else D(0)
        filled_avg_price: str | None = None
        if isinstance(request, LimitOrderRequest) and request.side is OrderSide.BUY:
            filled_avg_price = "1.05" if filled else None
        return SimpleNamespace(
            id=order_id,
            client_order_id=client_id,
            status=status,
            filled_qty=D(str(filled_qty)),
            filled_avg_price=filled_avg_price,
        )

    def cancel_order_by_id(self, order_id: object) -> None:
        self.calls.append("cancel_order_by_id")
        self.cancelled.append(str(order_id))
        self.overrides[str(order_id)] = "canceled"

    def replace_order_by_id(self, order_id: object, order_data: Any) -> Any:
        self.calls.append("replace_order_by_id")
        self.replaced.append((str(order_id), order_data))
        new_id = f"order-{len(self.orders_by_id) + 1}"
        self.orders_by_id[new_id] = order_data
        return SimpleNamespace(
            id=new_id,
            client_order_id=order_data.client_order_id,
            status="new",
            filled_qty=D(0),
            filled_avg_price=None,
        )


class FakeDataClient:
    def __init__(self, bars: dict[str, list[Any]], *, fail: bool = False) -> None:
        self.bars_by_symbol = bars
        self.fail = fail
        self.calls: list[Any] = []

    def get_stock_bars(self, request_params: Any) -> Any:
        self.calls.append(request_params)
        if self.fail:
            raise RuntimeError("historical bars unavailable")
        body = {
            symbol: self.bars_by_symbol.get(symbol, ())
            for symbol in request_params.symbol_or_symbols
        }
        return SimpleNamespace(data=body)


def asset(symbol: str, *, overnight_tradable: bool = True) -> Any:
    attributes = ["overnight_tradable"] if overnight_tradable else []
    return SimpleNamespace(
        id=f"id-{symbol}",
        status="active",
        asset_class="us_equity",
        symbol=symbol,
        tradable=True,
        attributes=attributes,
    )


def daily_bars(close: str, volume: str) -> list[Any]:
    return [
        SimpleNamespace(
            timestamp=datetime(2026, 11, 5, 10, 0, tzinfo=ET),
            close=D("0.98"),
            volume=D("100"),
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 11, 6, 10, 0, tzinfo=ET),
            close=D("1.00"),
            volume=D("100"),
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 11, 9, 9, 30, tzinfo=ET),
            close=D(close),
            volume=D(volume),
        ),
    ]


def trade(
    seconds: int, price: str, size: int = 100, *, base: int = START, iid: InstrumentId = IID
) -> TradeTick:
    ts = base + seconds * SEC
    return TradeTick(
        iid,
        Price.from_str(price),
        Quantity.from_int(size),
        AggressorSide.NO_AGGRESSOR,
        TradeId(f"{iid}-{ts}"),
        ts,
        ts,
    )


def quote(
    seconds: int,
    bid: str,
    ask: str,
    *,
    base: int = START,
    iid: InstrumentId = IID,
) -> QuoteTick:
    ts = base + seconds * SEC
    return QuoteTick(
        iid,
        Price.from_str(bid),
        Price.from_str(ask),
        Quantity.from_int(100),
        Quantity.from_int(100),
        ts,
        ts,
    )


def replay(
    feed: FakeFeed,
    *,
    base: int = START,
    iid: InstrumentId = IID,
    size: int = 100,
    entry_hook: Any = None,
) -> None:
    """The C session's warm-up, flag, first leg and ask quote, with the live clock."""

    for seconds, price, warm_size in (
        (0, "1.0000", size),
        (25, "1.0100", size),
        (26, "1.0100", size),
        (30, "1.0000", size),
        (31, "1.0300", 500),
        (32, "1.0400", 500),
    ):
        feed.clock.value = base + seconds * SEC
        feed.on_trade(trade(seconds, price, warm_size, base=base, iid=iid))
    feed.clock.value = base + 32 * SEC
    feed.on_quote(quote(32, "1.0400", "1.0600", base=base, iid=iid))
    feed.clock.value = base + 33 * SEC
    feed.on_trade(trade(33, "1.0500", 500, base=base, iid=iid))
    for seconds in range(34, 39):
        feed.clock.value = base + seconds * SEC
        feed.on_trade(trade(seconds, "1.0200", 100, base=base, iid=iid))
    feed.clock.value = base + 38 * SEC
    if entry_hook is not None:
        entry_hook()
    feed.on_quote(quote(38, "1.0200", "1.0300", base=base, iid=iid))


def replay_pair(feed: FakeFeed, iids: tuple[InstrumentId, ...], *, base: int = START) -> None:
    """The same surge driven for two symbols without moving the other's clock."""

    for seconds, price, size in (
        (0, "1.0000", 100),
        (25, "1.0100", 100),
        (26, "1.0100", 100),
        (30, "1.0000", 100),
        (31, "1.0300", 500),
        (32, "1.0400", 500),
    ):
        feed.clock.value = base + seconds * SEC
        for iid in iids:
            feed.on_trade(trade(seconds, price, size, base=base, iid=iid))
    feed.clock.value = base + 32 * SEC
    for iid in iids:
        feed.on_quote(quote(32, "1.0400", "1.0600", base=base, iid=iid))
    feed.clock.value = base + 33 * SEC
    for iid in iids:
        feed.on_trade(trade(33, "1.0500", 500, base=base, iid=iid))
    for seconds in range(34, 39):
        feed.clock.value = base + seconds * SEC
        for iid in iids:
            feed.on_trade(trade(seconds, "1.0200", 100, base=base, iid=iid))
    feed.clock.value = base + 38 * SEC
    for iid in iids:
        feed.on_quote(quote(38, "1.0200", "1.0300", base=base, iid=iid))


def noop_replay(feed: FakeFeed) -> None:
    """Keep the clock where the test set it; no ticks cross the segment."""


def switch_replay(feed: FakeFeed) -> None:
    """Cross the overnight/pre boundary so the runner must load the next segment."""

    feed.clock.value = PRE_SWITCH_CLOCK + 20 * SEC


def rth_close_replay(feed: FakeFeed) -> None:
    """Cross the RTH/post boundary without a fill."""

    feed.clock.value = POST_CLOCK


def post_replay(feed: FakeFeed) -> None:
    """The same surge in the post session, then a higher trade that moves the trail."""

    replay(feed, base=POST_CLOCK)
    feed.clock.value = POST_CLOCK + 40 * SEC
    feed.on_trade(trade(40, "1.1000", 500, base=POST_CLOCK))


def post_fill_then_overnight_replay(feed: FakeFeed) -> None:
    """Fill OMH in POST, then cross the 20:00 boundary."""

    replay(feed, base=POST_CLOCK)
    feed.clock.value = OVERNIGHT_CLOCK


def post_pair_then_overnight_replay(feed: FakeFeed) -> None:
    """Fill two names in POST, then cross the 20:00 boundary."""

    replay_pair(feed, (IID, DDD_IID), base=POST_CLOCK)
    feed.clock.value = OVERNIGHT_CLOCK


def pre_fill_then_rth_replay(feed: FakeFeed) -> None:
    """Fill OMH in PRE, then cross the 09:30 boundary."""

    replay(feed, base=PRE_OPEN_CLOCK)
    feed.clock.value = RTH_AFTER_OPEN


def rth_after_open_replay(feed: FakeFeed) -> None:
    """Drive the same surge again after the PRE/RTH boundary."""

    replay(feed, base=RTH_AFTER_OPEN)


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
        tap: Any = None,
        tap_symbols: tuple[str, ...] = (),
        on_page: Any = None,
    ) -> None:
        self.instruments = instruments
        self.on_trade = on_trade
        self.on_quote = on_quote
        self.api_key = api_key
        self.secret_key = secret_key
        self.feed = feed
        self.clock = clock
        self.replay = replay
        self.tap = tap
        self.tap_symbols = tap_symbols
        self.on_page = on_page
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
    baseline_dir: Path | None = None,
    replays: list[Any] | None = None,
    feed_log: list[FakeFeed] | None = None,
    universe: bool = False,
    data: Any = None,
    symbols: str = "OMH.ALPACA",
    state: Path | None = None,
    config: Path | None = None,
    feed_tap: bool = False,
    feed_tap_universe: Path | None = None,
) -> int:
    calls = {"index": 0}

    def feed_factory(instruments: Any, **kwargs: Any) -> FakeFeed:
        index = calls["index"]
        calls["index"] += 1
        chosen = replays[index] if replays is not None else replay
        feed = FakeFeed(instruments, clock=clock, replay=chosen, **kwargs)
        if feed_log is not None:
            feed_log.append(feed)
        return feed

    def sleep(seconds: float) -> None:
        mono.sleep(seconds)
        clock.value += int(seconds * SEC)

    argv = [
        "--config",
        str(config if config is not None else write_config(tmp_path)),
    ]
    if universe:
        argv.append("--universe")
    else:
        argv += ["--symbols", symbols]
    if baseline_dir is not None:
        argv += ["--baseline-dir", str(baseline_dir)]
    else:
        argv += ["--baseline", str(write_baseline(tmp_path))]
    argv += ["--state", str(state if state is not None else tmp_path / "state"), "--seconds", "1"]
    if dry_run:
        argv.append("--dry-run")
    if feed_tap:
        argv.append("--feed-tap")
    if feed_tap_universe is not None:
        argv += ["--feed-tap-universe", str(feed_tap_universe)]
    return main(
        argv,
        client_factory=lambda **_: client,
        data_factory=lambda **_: data if data is not None else FakeDataClient({}),
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
    monkeypatch.setattr(
        c_live_main_module,
        "DEFAULT_LEASE_ROOT",
        tmp_path / "locks",
        raising=False,
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def receipt(tmp_path: Path) -> dict[str, Any]:
    paths = list((tmp_path / "reports/paper-c").glob("*/session.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text())


def arm(
    client: FakeTradingClient,
    data: FakeDataClient,
    *,
    retained: frozenset[str] = frozenset(),
    mover_armed: frozenset[str] = frozenset(),
    max_armed_symbols: int = 5,
) -> tuple[Any, str | None]:
    segment = segment_start(POST_CLOCK)[0]
    assert segment is not None
    return _arm_universe(
        client=client,  # type: ignore[arg-type]
        data=data,  # type: ignore[arg-type]
        segment=segment,
        max_armed_symbols=max_armed_symbols,
        retained=retained,
        mover_armed=mover_armed,
        now=datetime.fromtimestamp(POST_CLOCK / NS, tz=UTC),
    )


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
    root = live_env / "locks"
    lease = WriterLease(AccountScope("ALPACA", ACCOUNT), root, "other-writer")
    lease.acquire()
    client = FakeTradingClient()
    try:
        with pytest.raises(SystemExit) as refusal:
            invoke(live_env, client, Clock(), Monotonic())
    finally:
        lease.close()
    assert refusal.value.code != 0
    assert "account already has a writer" in str(refusal.value.code)
    assert client.submitted == []


def test_the_account_lease_is_one_fixed_file_not_the_state_directory(live_env: Path) -> None:
    assert invoke(live_env, FakeTradingClient(), Clock(), Monotonic()) == 0

    locks = list((live_env / "locks").glob("*.lock"))
    assert len(locks) == 1
    assert re.fullmatch(r"[0-9a-f]{64}\.lock", locks[0].name)
    assert ACCOUNT not in locks[0].name
    assert "C001" not in locks[0].name
    assert not (live_env / "state" / "writer.lock").exists()
    assert not (live_env / "state" / "locks").exists()


LEASE_HOLDER = f"""
import sys
import time
from pathlib import Path

from sextant.execution.custody import AccountScope, WriterLease

lease = WriterLease(AccountScope("ALPACA", "{ACCOUNT}"), Path(sys.argv[1]), "other-runner")
lease.acquire()
print("held", flush=True)
time.sleep(30)
"""


def test_two_starts_on_one_account_cannot_both_write(live_env: Path, tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    holder = subprocess.Popen(
        [sys.executable, "-c", LEASE_HOLDER, str(live_env / "locks")],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        second_client = FakeTradingClient()
        with pytest.raises(SystemExit) as refusal:
            invoke(
                live_env,
                second_client,
                Clock(),
                Monotonic(),
                state=live_env / "state-b",
            )
        assert refusal.value.code != 0
        assert "account already has a writer" in str(refusal.value.code)
        assert second_client.submitted == []
    finally:
        holder.terminate()
        holder.wait(10)


def test_a_mismatched_account_id_refuses_before_any_lock(live_env: Path) -> None:
    client = FakeTradingClient()
    config = write_config(live_env, account_id="C002")

    with pytest.raises(SystemExit) as refusal:
        invoke(live_env, client, Clock(), Monotonic(), config=config)

    assert refusal.value.code != 0
    assert "does not match the configured C paper account" in str(refusal.value.code)
    assert ACCOUNT not in str(refusal.value.code)
    assert "C002" not in str(refusal.value.code)
    assert not (live_env / "locks").exists()
    assert client.submitted == []


def test_a_mismatched_config_cannot_take_the_authenticated_writer_lease(
    live_env: Path, tmp_path: Path
) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    holder = subprocess.Popen(
        [sys.executable, "-c", LEASE_HOLDER, str(live_env / "locks")],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        client = FakeTradingClient()
        config = write_config(live_env, account_id="C002")
        with pytest.raises(SystemExit) as refusal:
            invoke(
                live_env,
                client,
                Clock(),
                Monotonic(),
                state=live_env / "state-b",
                config=config,
            )
        assert refusal.value.code != 0
        assert "does not match the configured C paper account" in str(refusal.value.code)
        assert len(list((live_env / "locks").glob("*.lock"))) == 1
        assert client.submitted == []
    finally:
        holder.terminate()
        holder.wait(10)


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
    assert written["final_segment"] == "RTH"
    assert written["segment"]["name"] == "RTH"
    assert [row["segment"] for row in written["commands"]] == ["RTH"]


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
    assert D(str(buy.qty)) == D("120")  # flow-bound: 0.05 x 2472 / 1.03

    assert isinstance(trail, TrailingStopOrderRequest)
    assert trail.side is OrderSide.SELL
    assert trail.time_in_force is TimeInForce.GTC
    assert trail.symbol == "OMH"
    assert D(str(trail.qty)) == D("120")
    assert D(str(trail.trail_percent)) == D("2.5")

    written = receipt(live_env)
    assert written["tier"] == "BROKER-PAPER"
    assert written["account_suffix"] == SUFFIX
    assert written["symbols"] == ["OMH.ALPACA"]
    assert written["dry_run"] is False
    assert [row["kind"] for row in written["commands"]] == ["LIMIT", "TRAILING_STOP"]
    assert [row["side"] for row in written["commands"]] == ["BUY", "SELL"]
    assert written["commands"][0]["status"] == "FILLED"
    assert written["commands"][0]["fill"] == "120"
    assert written["commands"][1]["trail"] == "2.5"
    assert written["commands"][1]["status"] == "FILLED"
    assert written["protection_cid"] == trail.client_order_id
    assert written["entry_params_hash"]
    assert written["baseline"]["feed"] == "sip"
    assert written["final_segment"] == "RTH"
    assert written["segment"]["name"] == "RTH"
    assert [row["segment"] for row in written["commands"]] == ["RTH", "RTH"]

    captured = capsys.readouterr()
    assert API_KEY not in captured.out + captured.err
    assert SECRET not in captured.out + captured.err
    assert ACCOUNT not in captured.out + captured.err


def test_a_fresh_balance_read_caps_the_entry_in_the_live_runner(live_env: Path) -> None:
    client = FakeTradingClient()

    def cap_before_entry() -> None:
        client.account.buying_power = "100"

    def capped(feed: FakeFeed) -> None:
        replay(feed, entry_hook=cap_before_entry)

    assert invoke(live_env, client, Clock(), Monotonic(), replays=[capped]) == 0

    buy = client.submitted[0]
    assert isinstance(buy, LimitOrderRequest)
    assert buy.side is OrderSide.BUY
    # Basis 10000 (risk 333); the fresh 100 buying power caps at 97 shares.
    assert D(str(buy.qty)) == D("97")
    assert client.calls.count("get_account") == 3


def test_each_segment_freezes_its_basis_from_that_segments_balance(live_env: Path) -> None:
    client = FakeTradingClient()

    def close_overnight(feed: FakeFeed) -> None:
        feed.clock.value = PRE_OPEN_CLOCK
        client.account.equity = "5000"
        client.account.buying_power = "5000"

    def pre_surge(feed: FakeFeed) -> None:
        replay(feed, base=PRE_OPEN_CLOCK, size=100_000)

    baseline_dir = write_baseline_dir(live_env, segments=("OVERNIGHT", "PRE"))
    code = invoke(
        live_env,
        client,
        Clock(OVERNIGHT_CLOCK),
        Monotonic(),
        baseline_dir=baseline_dir,
        replays=[close_overnight, pre_surge],
    )

    assert code == 0
    buys = [
        order
        for order in client.submitted
        if isinstance(order, LimitOrderRequest) and order.side is OrderSide.BUY
    ]
    assert len(buys) == 1
    # PRE basis 5000: planned 10 over the 0.06 stop = 166 shares, not 333.
    assert D(str(buys[0].qty)) == D("166")
    assert client.calls.count("get_account") == 4


def test_a_failed_balance_read_refuses_the_entry_and_keeps_the_startup_number_out(
    live_env: Path,
) -> None:
    client = FakeTradingClient()

    def fail_before_entry() -> None:
        client.fail_account_reads = True

    def failing(feed: FakeFeed) -> None:
        replay(feed, entry_hook=fail_before_entry)

    assert invoke(live_env, client, Clock(), Monotonic(), replays=[failing]) == 0

    assert client.submitted == []
    assert client.calls.count("get_account") == 3
    assert receipt(live_env)["commands"] == []


def test_one_entry_wave_never_spends_the_same_buying_power_twice(live_env: Path) -> None:
    """The sender commits buying power, so the next intent must read it again."""

    class CommittingClient(FakeTradingClient):
        def submit_order(self, order_data: Any) -> Any:
            if isinstance(order_data, LimitOrderRequest) and order_data.side is OrderSide.BUY:
                committed = D(str(order_data.qty)) * D(str(order_data.limit_price))
                self.account.buying_power = str(D(self.account.buying_power) - committed)
            return super().submit_order(order_data)

    symbols = ("OMH", "DDD")
    identifiers = tuple(InstrumentId.from_str(f"{symbol}.ALPACA") for symbol in symbols)
    client = CommittingClient(
        assets=tuple(asset(symbol) for symbol in symbols), trail_ack_status="new"
    )
    data = FakeDataClient({symbol: daily_bars("1.10", "500") for symbol in symbols})

    def wave(feed: FakeFeed) -> None:
        for seconds, price, size in (
            (0, "1.0000", 100),
            (25, "1.0100", 100),
            (26, "1.0100", 100),
            (30, "1.0000", 100),
            (31, "1.0300", 500),
            (32, "1.0400", 500),
        ):
            feed.clock.value = START + seconds * SEC
            for iid in identifiers:
                feed.on_trade(trade(seconds, price, size, iid=iid))
        feed.clock.value = START + 32 * SEC
        for iid in identifiers:
            feed.on_quote(quote(32, "1.0400", "1.0600", iid=iid))
        feed.clock.value = START + 33 * SEC
        for iid in identifiers:
            feed.on_trade(trade(33, "1.0500", 500, iid=iid))
        for seconds in range(34, 38):
            feed.clock.value = START + seconds * SEC
            for iid in identifiers:
                feed.on_trade(trade(seconds, "1.0200", 100, iid=iid))
        for iid in identifiers:
            feed.on_quote(quote(37, "1.0200", "1.0300", iid=iid))
        feed.clock.value = START + 38 * SEC
        for iid in identifiers:
            feed.on_trade(trade(38, "1.0200", 100, iid=iid))
        client.account.buying_power = "100"
        feed.on_quote(quote(38, "1.0200", "1.0300", iid=identifiers[0]))

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=data,
        baseline_dir=write_baseline_dir(live_env, segments=("RTH",), symbols=symbols),
        replays=[wave],
    )

    buys = [
        order
        for order in client.submitted
        if isinstance(order, LimitOrderRequest) and order.side is OrderSide.BUY
    ]
    notional = sum(D(str(order.qty)) * D(str(order.limit_price)) for order in buys)
    assert code == 0
    # The first 97-share BUY commits 99.91; the second intent sees 0.09 left and
    # refuses instead of sizing against the stale 100.
    assert len(buys) == 1
    assert notional <= D("100")
    assert client.calls.count("get_account") == 4


@pytest.mark.parametrize("terminal_status", ["canceled", "expired", "rejected"])
def test_a_sized_entry_partial_fill_is_reconciled_and_protected(
    live_env: Path, terminal_status: str
) -> None:
    """A terminal entry must protect the shares it filled (fix3 item 2)."""

    class PartialThenTerminalClient(FakeTradingClient):
        actual_filled = D(0)

        def submit_order(self, order_data: Any) -> Any:
            ack = super().submit_order(order_data)
            if isinstance(order_data, LimitOrderRequest) and order_data.side is OrderSide.BUY:
                requested = D(str(order_data.qty))
                self.actual_filled = min(D("25"), requested)
                ack.filled_qty = self.actual_filled
                if requested > self.actual_filled:
                    ack.status = "partially_filled"
            return ack

        def get_order_by_client_id(self, client_id: str) -> Any:
            order = super().get_order_by_client_id(client_id)
            request, _ = self.orders_by_cid[client_id]
            if isinstance(request, LimitOrderRequest) and request.side is OrderSide.BUY:
                order.status = terminal_status
                order.filled_qty = self.actual_filled
            return order

    client = PartialThenTerminalClient(trail_ack_status="new")
    assert invoke(live_env, client, Clock(), Monotonic()) == 1

    protected = sum(
        D(str(request.qty)) for request in client.submitted if request.side is OrderSide.SELL
    )
    assert client.actual_filled == D("25")
    assert protected >= client.actual_filled
    written = receipt(live_env)
    entry = next(row for row in written["commands"] if row["side"] == "BUY")
    assert entry["fill"] == "25"


def test_an_unknown_order_state_stops_without_a_resubmit(live_env: Path) -> None:
    client = FakeTradingClient(ack_status="new", poll_status="new")
    assert invoke(live_env, client, Clock(), Monotonic()) == 1

    assert len(client.submitted) == 1
    assert client.client_polls
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


def test_c_polls_an_unfilled_entry_by_its_client_order_id(live_env: Path) -> None:
    """Finding 4: the SDK rejects a client id at get_order_by_id, so poll by cid."""

    client = FakeTradingClient(ack_status="new", validate_order_ids=True)
    assert invoke(live_env, client, Clock(), Monotonic()) == 0

    written = receipt(live_env)
    entry = written["commands"][0]
    assert entry["kind"] == "LIMIT"
    assert entry["status"] == "FILLED"
    assert entry["fill"] == "120"
    assert client.client_polls == [entry["cid"]]
    assert "get_order_by_id" not in client.calls


def test_c_counts_a_resting_protective_trail_as_placed(live_env: Path) -> None:
    """Finding 5: a working trail is placed; only entries and releases await FILLED."""

    client = FakeTradingClient(ack_status="filled", trail_ack_status="new", validate_order_ids=True)
    assert invoke(live_env, client, Clock(), Monotonic()) == 0

    written = receipt(live_env)
    trail = written["commands"][1]
    assert trail["kind"] == "TRAILING_STOP"
    assert trail["ack"] == "NEW"
    assert trail["status"] == "NEW"
    assert written["protection_cid"] == trail["cid"]
    assert client.client_polls == []
    assert "get_order_by_id" not in client.calls


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


def test_overnight_uses_the_boats_feed_and_its_own_baseline(live_env: Path) -> None:
    client = FakeTradingClient()
    feed_log: list[FakeFeed] = []
    baseline_dir = write_baseline_dir(live_env, segments=("OVERNIGHT",))

    code = invoke(
        live_env,
        client,
        Clock(OVERNIGHT_CLOCK),
        Monotonic(),
        baseline_dir=baseline_dir,
        replays=[noop_replay],
        feed_log=feed_log,
    )

    assert code == 0
    assert [feed.feed for feed in feed_log] == ["boats"]
    written = receipt(live_env)
    assert written["final_segment"] == "OVERNIGHT"
    assert written["segment"]["name"] == "OVERNIGHT"
    assert written["baseline"]["feed"] == "boats"
    assert client.submitted == []


def test_overnight_requires_overnight_tradable(live_env: Path) -> None:
    client = FakeTradingClient(overnight_tradable=False)
    baseline_dir = write_baseline_dir(live_env, segments=("OVERNIGHT",))

    with pytest.raises(SystemExit) as refusal:
        invoke(
            live_env,
            client,
            Clock(OVERNIGHT_CLOCK),
            Monotonic(),
            baseline_dir=baseline_dir,
        )

    assert "not overnight-eligible" in str(refusal.value.code)
    assert client.submitted == []


def test_overnight_refuses_a_halted_asset(live_env: Path) -> None:
    client = FakeTradingClient(overnight_halted=True)
    baseline_dir = write_baseline_dir(live_env, segments=("OVERNIGHT",))

    with pytest.raises(SystemExit) as refusal:
        invoke(
            live_env,
            client,
            Clock(OVERNIGHT_CLOCK),
            Monotonic(),
            baseline_dir=baseline_dir,
        )

    assert "not overnight-eligible" in str(refusal.value.code)
    assert client.submitted == []


def test_a_not_tradable_asset_refuses(live_env: Path) -> None:
    client = FakeTradingClient(tradable=False)

    with pytest.raises(SystemExit) as refusal:
        invoke(live_env, client, Clock(START), Monotonic())

    assert "not tradable" in str(refusal.value.code)
    assert client.submitted == []


def test_a_missing_startup_baseline_refuses(live_env: Path) -> None:
    client = FakeTradingClient()
    empty = live_env / "no-baselines"
    empty.mkdir()

    with pytest.raises(SystemExit) as refusal:
        invoke(
            live_env,
            client,
            Clock(OVERNIGHT_CLOCK),
            Monotonic(),
            baseline_dir=empty,
        )

    assert "OVERNIGHT baseline is unavailable" in str(refusal.value.code)
    assert client.submitted == []


def test_a_segment_switch_recreates_the_feed_and_session(live_env: Path) -> None:
    client = FakeTradingClient()
    feed_log: list[FakeFeed] = []
    baseline_dir = write_baseline_dir(live_env)

    code = invoke(
        live_env,
        client,
        Clock(PRE_SWITCH_CLOCK),
        Monotonic(),
        baseline_dir=baseline_dir,
        replays=[switch_replay, noop_replay],
        feed_log=feed_log,
    )

    assert code == 0
    assert [feed.feed for feed in feed_log] == ["boats", "sip"]
    assert feed_log[0].stopped is True
    written = receipt(live_env)
    assert written["final_segment"] == "PRE"
    assert written["segment"]["name"] == "PRE"
    assert written["baseline"]["provenance"] == "pre baseline"
    assert written["commands"] == []
    assert client.submitted == []


def test_a_missing_next_baseline_stops_with_the_receipt(live_env: Path) -> None:
    client = FakeTradingClient()
    baseline_dir = write_baseline_dir(live_env, segments=("OVERNIGHT",))

    code = invoke(
        live_env,
        client,
        Clock(PRE_SWITCH_CLOCK),
        Monotonic(),
        baseline_dir=baseline_dir,
        replays=[switch_replay],
    )

    assert code == 1
    written = receipt(live_env)
    assert written["final_segment"] == "PRE"
    assert written["baseline"] is None
    assert any("PRE baseline is unavailable" in error for error in written["errors"])
    ledger = TrialLog(live_env / "trials.parquet")
    assert ledger.records[0]["state"] == "FAIL"


def test_a_non_rth_fill_rests_a_limit_and_reprices_it(live_env: Path) -> None:
    client = FakeTradingClient()
    baseline_dir = write_baseline_dir(live_env, segments=("POST",))

    code = invoke(
        live_env,
        client,
        Clock(POST_CLOCK),
        Monotonic(),
        baseline_dir=baseline_dir,
        replays=[post_replay],
    )

    assert code == 0
    buy, exit_order = client.submitted
    assert isinstance(buy, LimitOrderRequest)
    assert buy.side is OrderSide.BUY
    assert isinstance(exit_order, LimitOrderRequest)
    assert exit_order.side is OrderSide.SELL
    assert exit_order.time_in_force is TimeInForce.GTC
    assert exit_order.extended_hours is True
    assert D(str(exit_order.limit_price)) == D("1.02")
    assert exit_order.client_order_id is not None
    assert exit_order.client_order_id.endswith("-exit")

    assert client.cancelled == ["order-2"]
    assert len(client.replaced) == 1
    replaced_id, replacement = client.replaced[0]
    assert replaced_id == "order-2"
    assert replacement.client_order_id.endswith("-exit-r1")
    assert D(str(replacement.limit_price)) == D("1.07")

    written = receipt(live_env)
    assert [row["kind"] for row in written["commands"]] == [
        "LIMIT",
        "LIMIT",
        "CANCEL",
        "MODIFY",
    ]
    assert [row["side"] for row in written["commands"]] == [
        "BUY",
        "SELL",
        "SELL",
        "SELL",
    ]
    assert [row["segment"] for row in written["commands"]] == ["POST"] * 4
    assert written["commands"][1]["limit"] == "1.02"
    assert written["commands"][1]["status"] == "SUBMITTED"
    assert written["commands"][2]["status"] == "CANCELED"
    assert written["commands"][3]["ack"] == "NEW"
    assert written["commands"][3]["limit"] == "1.07"
    assert written["protection_cid"].endswith("-exit-r1")
    assert written["final_segment"] == "POST"


def test_a_rejected_limit_exit_stops_the_run_unprotected(live_env: Path) -> None:
    client = FakeTradingClient(exit_ack_status="rejected")
    baseline_dir = write_baseline_dir(live_env, segments=("POST",))

    code = invoke(
        live_env,
        client,
        Clock(POST_CLOCK),
        Monotonic(),
        baseline_dir=baseline_dir,
        replays=[post_replay],
    )

    assert code == 1
    assert len(client.submitted) == 2
    written = receipt(live_env)
    assert any("unprotected" in error for error in written["errors"])
    assert written["final_segment"] == "POST"
    assert written["protection_cid"] is None


def test_the_real_asset_shape_carries_overnight_tradable_in_attributes() -> None:
    from datetime import date

    from sextant.paper.c_live_main import _require_eligible
    from sextant.ranking.engine import Segment

    asset = SimpleNamespace(
        tradable=True,
        attributes=["fractional_eh_enabled", "has_options", "overnight_tradable"],
    )
    segment = Segment("OVERNIGHT", date(2026, 11, 9), 0, 1, "receipt")
    _require_eligible(asset, "AAPL", segment)


def test_the_real_asset_shape_refuses_when_the_attribute_is_absent() -> None:
    from datetime import date

    from sextant.paper.c_live_main import LiveRefusal, _require_eligible
    from sextant.ranking.engine import Segment

    asset = SimpleNamespace(tradable=True, attributes=["fractional_eh_enabled"])
    segment = Segment("OVERNIGHT", date(2026, 11, 9), 0, 1, "receipt")
    with pytest.raises(LiveRefusal, match="not overnight-eligible"):
        _require_eligible(asset, "AAPL", segment)


def test_the_universe_ranking_arms_the_slot_pool_and_drives_the_session(
    live_env: Path,
) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))
    data = FakeDataClient(ranks)
    feed_log: list[FakeFeed] = []

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=data,
        feed_log=feed_log,
    )

    assert code == 0
    assert len(feed_log) == 1
    assert set(feed_log[0].instruments) == {
        "OMH.ALPACA",
        "DDD.ALPACA",
        "CCC.ALPACA",
        "BBB.ALPACA",
        "AAA.ALPACA",
    }
    assert data.calls
    written = receipt(live_env)
    assert written["symbols"] == [
        "OMH.ALPACA",
        "DDD.ALPACA",
        "CCC.ALPACA",
        "BBB.ALPACA",
        "AAA.ALPACA",
    ]
    assert written["arming"][0]["eligible"] == 5
    assert written["arming"][0]["slots"] == 2
    assert written["arming"][0]["max_armed_symbols"] == 5
    assert written["arming"][0]["armed"] == [
        "OMH.ALPACA",
        "DDD.ALPACA",
        "CCC.ALPACA",
        "BBB.ALPACA",
        "AAA.ALPACA",
    ]
    assert written["commands"]
    assert client.submitted


def test_a_universe_run_rearms_at_each_segment_boundary(live_env: Path) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))
    data = FakeDataClient(ranks)
    feed_log: list[FakeFeed] = []

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=data,
        baseline_dir=write_baseline_dir(live_env),
        replays=[rth_close_replay, noop_replay],
        feed_log=feed_log,
    )

    assert code == 0
    assert len(feed_log) == 2
    assert [set(feed.instruments) for feed in feed_log] == [
        {"OMH.ALPACA", "DDD.ALPACA", "CCC.ALPACA", "BBB.ALPACA", "AAA.ALPACA"},
        {"OMH.ALPACA", "DDD.ALPACA", "CCC.ALPACA", "BBB.ALPACA", "AAA.ALPACA"},
    ]
    written = receipt(live_env)
    assert [arming["segment"] for arming in written["arming"]] == ["RTH", "POST"]
    assert written["final_segment"] == "POST"


def test_c_arms_five_names_in_score_order_not_candidate_count_or_symbol_order(
    live_env: Path,
) -> None:
    ranks = {
        "AAA": daily_bars("1.02", "300"),
        "BBB": daily_bars("1.04", "300"),
        "CCC": daily_bars("1.06", "300"),
        "DDD": daily_bars("1.08", "300"),
        "YYY": daily_bars("1.10", "300"),
        "ZZZ": daily_bars("1.12", "300"),
        "OMH": daily_bars("1.14", "500"),
    }
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=FakeDataClient(ranks),
    )

    assert code == 0
    written = receipt(live_env)
    assert written["symbols"] == [
        "OMH.ALPACA",
        "ZZZ.ALPACA",
        "YYY.ALPACA",
        "DDD.ALPACA",
        "CCC.ALPACA",
    ]
    assert written["arming"][0]["eligible"] == 7
    assert written["arming"][0]["max_armed_symbols"] == 5
    assert written["arming"][0]["slots"] == 2


def test_a_held_name_that_is_not_overnight_eligible_stays_charged_but_held_back(
    live_env: Path,
) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    client = FakeTradingClient(
        assets=(
            asset("OMH", overnight_tradable=False),
            asset("DDD"),
            asset("CCC"),
            asset("BBB"),
            asset("AAA"),
        )
    )
    feed_log: list[FakeFeed] = []

    code = invoke(
        live_env,
        client,
        Clock(POST_CLOCK),
        Monotonic(),
        universe=True,
        data=FakeDataClient(ranks),
        baseline_dir=write_baseline_dir(live_env),
        replays=[post_fill_then_overnight_replay, noop_replay],
        feed_log=feed_log,
    )

    assert code == 0
    assert [feed.feed for feed in feed_log] == ["sip", "boats"]
    written = receipt(live_env)
    assert written["final_segment"] == "OVERNIGHT"
    overnight = written["arming"][1]
    assert overnight["custody_open"] == 1
    assert overnight["held_back"] == ["OMH.ALPACA"]
    assert "OMH.ALPACA" not in overnight["armed"]


def test_every_filled_name_stays_in_custody_across_a_segment_boundary(
    live_env: Path,
) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))
    feed_log: list[FakeFeed] = []

    code = invoke(
        live_env,
        client,
        Clock(POST_CLOCK),
        Monotonic(),
        universe=True,
        data=FakeDataClient(ranks),
        baseline_dir=write_baseline_dir(live_env, symbols=tuple(ranks)),
        replays=[post_pair_then_overnight_replay, noop_replay],
        feed_log=feed_log,
    )

    assert code == 0
    assert [feed.feed for feed in feed_log] == ["sip", "boats"]
    written = receipt(live_env)
    assert written["final_segment"] == "OVERNIGHT"
    assert written["arming"][1]["custody_open"] == 2
    assert {"OMH.ALPACA", "DDD.ALPACA"} <= set(written["arming"][1]["armed"])


def test_a_held_name_is_not_bought_again_in_a_later_segment(live_env: Path) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))

    code = invoke(
        live_env,
        client,
        Clock(PRE_OPEN_CLOCK),
        Monotonic(),
        universe=True,
        data=FakeDataClient(ranks),
        baseline_dir=write_baseline_dir(live_env, segments=("PRE", "RTH")),
        replays=[pre_fill_then_rth_replay, rth_after_open_replay],
    )

    assert code == 0
    buys = [
        order
        for order in client.submitted
        if isinstance(order, LimitOrderRequest)
        and order.side is OrderSide.BUY
        and order.symbol == "OMH"
    ]
    assert len(buys) == 1


def test_c_retains_held_and_working_symbols_instead_of_only_the_position_count(
    tmp_path: Path,
) -> None:
    from sextant.paper.c_live_main import _retained_symbols

    scope = AccountScope("alpaca", "fixture")
    book = Custody(scope, tmp_path / "custody.json", create=True)
    snapshot = AccountSnapshot(
        scope,
        1,
        {"HELD.ALPACA": D(1), "FLAT.ALPACA": D(0)},
        {"HELD.ALPACA": PositionAuthority(D(1), "fixture")},
        (
            OrderFact("working", "WORKING.ALPACA", "BUY", D(1), D(0), "NEW", "working"),
            OrderFact("held", "HELD.ALPACA", "SELL", D(1), D(0), "NEW", "held"),
            OrderFact("done", "DONE.ALPACA", "BUY", D(1), D(1), "FILLED", "done"),
        ),
        True,
        1,
        "fixture",
    )
    assert book.observe(snapshot, now=1)
    assert _retained_symbols(book) == frozenset({"HELD.ALPACA", "WORKING.ALPACA"})


def test_c_refuses_a_missing_symbol_snapshot_explicitly(tmp_path: Path) -> None:
    from sextant.paper.c_live_main import LiveRefusal, _retained_symbols

    book = Custody(AccountScope("alpaca", "fixture"), tmp_path / "custody.json", create=True)
    with pytest.raises(LiveRefusal, match="custody symbols unavailable"):
        _retained_symbols(book)


def test_an_empty_universe_refuses_without_arming(live_env: Path) -> None:
    client = FakeTradingClient(assets=())
    data = FakeDataClient({})
    feed_log: list[FakeFeed] = []

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=data,
        feed_log=feed_log,
    )

    assert code == 1
    assert feed_log == []
    assert data.calls == []
    assert "get_asset" not in client.calls
    assert client.submitted == []
    written = receipt(live_env)
    assert written["symbols"] == []
    assert written["arming"][0]["armed"] == []
    assert any("no eligible symbols" in error for error in written["errors"])
    rows = TrialLog(live_env / "trials.parquet").records
    assert len(rows) == 1
    assert rows[0]["state"] == "FAIL"


def test_an_unusable_universe_ranking_refuses_without_arming(live_env: Path) -> None:
    client = FakeTradingClient(assets=(asset("OMH"),))
    data = FakeDataClient({}, fail=True)
    feed_log: list[FakeFeed] = []

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=data,
        feed_log=feed_log,
    )

    assert code == 1
    assert feed_log == []
    assert data.calls
    assert "get_asset" not in client.calls
    written = receipt(live_env)
    assert written["symbols"] == []
    assert written["arming"][0]["eligible"] == 0
    assert any("universe ranking failed" in error for error in written["errors"])
    rows = TrialLog(live_env / "trials.parquet").records
    assert len(rows) == 1
    assert rows[0]["state"] == "FAIL"


def test_universe_and_symbols_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as refused:
        main(
            [
                "--config",
                str(write_config(tmp_path)),
                "--symbols",
                "OMH.ALPACA",
                "--universe",
                "--baseline",
                str(write_baseline(tmp_path)),
                "--state",
                str(tmp_path / "state"),
            ]
        )
    assert refused.value.code == 2


@pytest.mark.parametrize("raise_on", [1, 2])
def test_a_custody_refusal_still_writes_a_receipt_and_a_fail_row(
    live_env: Path, monkeypatch: pytest.MonkeyPatch, raise_on: int
) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))
    calls = {"count": 0}
    real = c_live_main_module._retained_symbols

    def refuses(book: Custody) -> frozenset[str]:
        calls["count"] += 1
        if calls["count"] == raise_on:
            raise c_live_main_module.LiveRefusal("custody symbols unavailable for C arming")
        return real(book)

    monkeypatch.setattr(c_live_main_module, "_retained_symbols", refuses)

    code = invoke(
        live_env,
        client,
        Clock(POST_CLOCK),
        Monotonic(),
        universe=True,
        data=FakeDataClient(ranks),
        baseline_dir=write_baseline_dir(live_env, symbols=tuple(ranks)),
        replays=[noop_replay],
    )

    assert code == 1
    assert client.submitted == []
    written = receipt(live_env)
    assert written["final_segment"] == "POST"
    assert "custody symbols unavailable for C arming" in " ".join(written["errors"])
    if raise_on == 1:
        assert written["symbols"] == []
        assert written["arming"][0]["custody_open"] is None
        assert written["arming"][0]["armed"] == []
    else:
        assert written["symbols"]
        assert written["arming"][0]["custody_open"] == 0
    rows = TrialLog(live_env / "trials.parquet").records
    assert [row["state"] for row in rows] == ["FAIL"]
    assert "custody symbols unavailable" in rows[0]["error"]


@pytest.mark.parametrize("mode", ["failed", "empty"])
def test_a_failed_or_empty_boundary_ranking_keeps_the_held_name(live_env: Path, mode: str) -> None:
    ranks = {
        "OMH": daily_bars("1.10", "500"),
        "DDD": daily_bars("1.08", "300"),
        "CCC": daily_bars("1.06", "300"),
        "BBB": daily_bars("1.04", "300"),
        "AAA": daily_bars("1.02", "300"),
    }
    data = FakeDataClient(ranks)
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))

    def break_the_ranking(feed: FakeFeed) -> None:
        post_fill_then_overnight_replay(feed)
        if mode == "failed":
            data.fail = True
        else:
            data.bars_by_symbol.clear()

    code = invoke(
        live_env,
        client,
        Clock(POST_CLOCK),
        Monotonic(),
        universe=True,
        data=data,
        baseline_dir=write_baseline_dir(live_env, symbols=tuple(ranks)),
        replays=[break_the_ranking, noop_replay],
    )

    assert code == 1
    written = receipt(live_env)
    assert written["final_segment"] == "OVERNIGHT"
    overnight = written["arming"][1]
    assert overnight["custody_open"] == 1
    assert overnight["armed"] == ["OMH.ALPACA"]
    assert written["symbols"] == ["OMH.ALPACA"]
    expected = (
        "universe ranking failed"
        if mode == "failed"
        else "no eligible symbols for the OVERNIGHT session"
    )
    assert expected in " ".join(written["errors"])
    rows = TrialLog(live_env / "trials.parquet").records
    assert [row["state"] for row in rows] == ["FAIL"]


@pytest.mark.parametrize("mode", ["failed", "empty"])
def test_a_failed_or_empty_ranking_arms_the_retained_names(
    mode: str,
) -> None:
    data = FakeDataClient({"M0": daily_bars("1.10", "500")})
    if mode == "failed":
        data.fail = True
    else:
        data.bars_by_symbol.clear()
    retained = frozenset({"OMH.ALPACA", "DDD.ALPACA"})
    client = FakeTradingClient(
        assets=(asset("M0"), asset("OMH"), asset("DDD")),
    )

    arming, failure = arm(
        client,
        data,
        retained=retained,
        mover_armed=frozenset({"DDD.ALPACA"}),
    )

    assert failure is not None
    assert arming.custody_open == 2
    assert arming.armed == ("DDD.ALPACA", "OMH.ALPACA")
    assert arming.mover_armed == frozenset({"DDD.ALPACA"})


def test_the_retained_names_join_the_arming_in_sorted_order() -> None:
    retained = frozenset(f"Z{index}.ALPACA" for index in range(8))

    arming, failure = arm(
        FakeTradingClient(assets=(asset("M0"),)),
        FakeDataClient({"M0": daily_bars("1.10", "500")}),
        retained=retained,
    )

    assert failure is None
    assert arming.armed == tuple(sorted(retained))
    assert len(arming.armed) == 8


def test_the_mover_arm_is_the_allocators_own_membership() -> None:
    ranks = {f"M{index}": daily_bars("1.10", "500") for index in range(5)}
    assets = tuple(asset(symbol) for symbol in ("OLD", *ranks))

    arming, failure = arm(
        FakeTradingClient(assets=assets),
        FakeDataClient(ranks),
        retained=frozenset({"OLD.ALPACA"}),
    )

    assert failure is None
    assert arming.armed == (
        "M0.ALPACA",
        "M1.ALPACA",
        "M2.ALPACA",
        "M3.ALPACA",
        "OLD.ALPACA",
    )
    assert arming.mover_armed == frozenset({"M0.ALPACA", "M1.ALPACA", "M2.ALPACA", "M3.ALPACA"})


def test_the_receipt_records_the_allocators_mover_membership(live_env: Path) -> None:
    ranks = {f"M{index}": daily_bars("1.10", "500") for index in range(5)}
    client = FakeTradingClient(assets=tuple(asset(symbol) for symbol in ranks))

    assert (
        invoke(
            live_env,
            client,
            Clock(),
            Monotonic(),
            universe=True,
            data=FakeDataClient(ranks),
            baseline_dir=write_baseline_dir(live_env, symbols=tuple(ranks)),
        )
        == 0
    )

    written = receipt(live_env)
    assert written["arming"][0]["mover_armed"] == sorted(f"M{index}.ALPACA" for index in range(5))


def test_a_dotted_ticker_maps_to_its_bare_symbol_in_the_request() -> None:
    command = OrderCommand(
        client_order_id="",
        instrument="BRK.B.ALPACA",
        side="BUY",
        quantity=D(1),
        order_type="LIMIT",
        time_in_force="DAY",
        limit_price=D("1.00"),
        trail_price=None,
    )

    request = _request_for(command, "cid", extended_hours=False)

    assert isinstance(request, LimitOrderRequest)
    assert request.symbol == "BRK.B"


def test_a_dotted_ticker_maps_to_its_bare_symbol_in_the_house_cid() -> None:
    command = OrderCommand(
        client_order_id="",
        instrument="BRK.B.ALPACA",
        side="BUY",
        quantity=D(1),
        order_type="LIMIT",
        time_in_force="DAY",
        limit_price=D("1.00"),
        trail_price=None,
    )

    account = PaperAccount(
        lane="alpaca-paper-c",
        account_id="C001",
        client_id="c-live-proof",
        namespace="C001",
        sessions=(Session.RTH,),
    )

    cid = _house_cid(account, command)

    assert cid == "C001-BRK.B-buy-limit-1"


def test_a_universe_run_can_arm_and_order_a_dotted_ticker(live_env: Path) -> None:
    brk = InstrumentId.from_str("BRK.B.ALPACA")
    ranks = {"BRK.B": daily_bars("1.10", "500")}
    client = FakeTradingClient(assets=(asset("BRK.B"),))

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        universe=True,
        data=FakeDataClient(ranks),
        baseline_dir=write_baseline_dir(live_env, symbols=("BRK.B",)),
        replays=[lambda feed: replay(feed, iid=brk)],
    )

    assert code == 0
    assert client.submitted
    assert {order.symbol for order in client.submitted} == {"BRK.B"}
    assert receipt(live_env)["symbols"] == ["BRK.B.ALPACA"]


def test_a_completed_session_appends_one_full_identity_row(live_env: Path) -> None:
    ledger = live_env / "session-ledger.parquet"
    assert invoke(live_env, FakeTradingClient(), Clock(), Monotonic(), ledger=ledger) == 0

    written = receipt(live_env)
    rows = TrialLog(ledger).records
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "COMPLETE"
    config = json.loads(row["config"])
    params = json.loads(row["params"])
    assert config["arm_id"] == "paper-c-24x5"
    assert config["arm_run_id"] == written["receipt_id"]
    assert re.fullmatch(r"[0-9a-f]{40}", config["implementation_sha"])
    assert config["factor_mask"] == []
    assert config["sandbox_config_hash"] == snapshot_hash(config["sandbox_config"])
    assert config["evidence_weights_hash"] == snapshot_hash(config["evidence_weights"])
    assert config["params_hash"] == snapshot_hash(params)
    assert config["tier"] == "BROKER-PAPER"
    assert config["block_set_id"]
    assert config["funding_divergent_session_count"] is None
    assert config["funding_unverified_session_count"] is None
    assert config["condition_returns"] == {}
    assert params["entry_params_hash"] == written["entry_params_hash"]
    assert params["symbols"] == ["OMH.ALPACA"]
    assert "pnl" not in json.dumps(params).lower()
    assert not (live_env / "reports/research/trials.parquet").exists()


def test_a_ledger_failure_keeps_the_receipt_and_exits_non_zero(
    live_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = live_env / "not-a-directory"
    blocker.write_text("a file cannot hold a ledger")
    ledger = blocker / "trials.parquet"

    code = invoke(live_env, FakeTradingClient(), Clock(), Monotonic(), ledger=ledger)

    assert code == 1
    written = receipt(live_env)
    assert written["commands"]
    assert "trial ledger refused" in capsys.readouterr().err
    assert not (live_env / "reports/research/trials.parquet").exists()


def test_the_feed_tap_is_off_by_default_and_writes_no_sidecar(live_env: Path) -> None:
    feeds: list[FakeFeed] = []

    assert invoke(live_env, FakeTradingClient(), Clock(), Monotonic(), feed_log=feeds) == 0

    assert feeds and feeds[0].tap is None
    assert feeds[0].tap_symbols == ()
    assert not list((live_env / "reports/paper-c").glob("*/feed-tap.jsonl"))


def test_the_feed_tap_reads_the_ranked_universe_and_shares_the_receipt_directory(
    live_env: Path,
) -> None:
    universe = live_env / "universe.json"
    universe.write_text(json.dumps({"rows": [{"symbol": "OMH"}, {"symbol": "EXTRA"}]}))
    feeds: list[FakeFeed] = []
    client = FakeTradingClient()

    code = invoke(
        live_env,
        client,
        Clock(),
        Monotonic(),
        feed_tap=True,
        feed_tap_universe=universe,
        replays=[lambda feed: None],
        feed_log=feeds,
    )

    assert code == 0
    assert feeds and isinstance(feeds[0].tap, FeedTap)
    assert feeds[0].tap_symbols == ("EXTRA",)
    assert client.submitted == []
    sidecars = list((live_env / "reports/paper-c").glob("*/feed-tap.jsonl"))
    assert len(sidecars) == 1
    assert (sidecars[0].parent / "session.json").exists()


def test_a_missing_feed_tap_universe_is_refused_before_the_broker(live_env: Path) -> None:
    client = FakeTradingClient()
    feeds: list[FakeFeed] = []

    with pytest.raises(SystemExit, match="feed tap universe unavailable"):
        invoke(
            live_env,
            client,
            Clock(),
            Monotonic(),
            feed_tap=True,
            feed_tap_universe=live_env / "missing.json",
            feed_log=feeds,
        )

    assert client.calls == []
    assert feeds == []


def test_a_feed_tap_universe_requires_the_feed_tap(live_env: Path) -> None:
    with pytest.raises(SystemExit, match="requires --feed-tap"):
        invoke(
            live_env,
            FakeTradingClient(),
            Clock(),
            Monotonic(),
            feed_tap_universe=live_env / "universe.json",
        )
