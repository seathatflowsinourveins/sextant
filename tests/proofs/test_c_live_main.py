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
from sextant.execution.custody import (
    AccountScope,
    WriterLease,
)
from sextant.paper.c_live_main import (
    _arm_universe,
    _equity_ladder,
    main,
)
from sextant.ranking.baseline import (
    BaselineSample,
    BaselineTable,
    dump_baseline,
    segment_start,
)

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
        exchange="NASDAQ",
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
    feed_factory_override: Any = None,
    client_factory_override: Any = None,
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
        client_factory=client_factory_override or (lambda **_: client),
        data_factory=lambda **_: data if data is not None else FakeDataClient({}),
        feed_factory=feed_factory_override or feed_factory,
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
