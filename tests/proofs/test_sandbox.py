"""Pre-stream S boundaries; fixtures provide no feed or trading authority."""

import asyncio
import hashlib
import json
from decimal import Decimal

import pytest
from nautilus_trader.common import Environment
from nautilus_trader.execution import FixedFeeModel, StaticLatencyModel
from nautilus_trader.model import Money

from sextant.sandbox.node import PrestreamFeedFactory, SandboxBinding, build_plan, build_shell
from sextant.sandbox.recorded import read_snapshot


def plan():
    return build_plan(
        bindings=(
            SandboxBinding("fixture-a", "S0A", "S0A-001", "S0A-001", "S0A"),
            SandboxBinding("fixture-b", "S0B", "S0B-001", "S0B-001", "S0B"),
        ),
        starting_balance=Money.from_str("10000 USD"),
        leverage=Decimal(1),
        fee_model=FixedFeeModel(Money.from_str("0 USD")),
        latency_model=StaticLatencyModel(),
        authority="FIXTURE ONLY: upstream S0 routing drill, not calibrated costs",
    )


def test_sandbox_has_distinct_issued_accounts_and_native_simulated_execution():
    p = plan()
    assert p.config.environment == Environment.SANDBOX
    assert not p.config.risk_engine.bypass
    assert set(p.clients) == {"S0A", "S0B"}
    for name, client in p.clients.items():
        assert str(client.account_id).split("-", 1)[0] == name
        assert str(client.venue) == "ALPACA"
        assert client.use_random_ids
        assert client.reject_stop_orders
        assert not client.bar_execution
        assert not client.trade_execution
    assert p.connection_state == "DISABLED"


def test_alpaca_issuer_and_reused_order_namespace_are_refused():
    with pytest.raises(ValueError, match="issuer"):
        SandboxBinding("a", "S0A", "ALPACA-001", "S0A-001", "S0A")
    p = plan()
    with pytest.raises(ValueError, match="distinct"):
        build_plan(
            bindings=(p.bindings[0], p.bindings[0]),
            starting_balance=Money.from_str("10000 USD"),
            leverage=Decimal(1),
            fee_model=FixedFeeModel(Money.from_str("0 USD")),
            latency_model=StaticLatencyModel(),
            authority="FIXTURE ONLY",
        )


def test_native_node_build_is_inert_and_disposes_without_a_connection():
    shell = build_shell(plan(), arm_id="fixture-a", strategies=())
    try:
        assert not shell.is_running
        assert shell.environment == Environment.SANDBOX
    finally:
        shell.dispose()


def test_feed_connection_is_disabled_even_if_called_directly(monkeypatch):
    created = []
    original = PrestreamFeedFactory.create

    def capture(**kwargs):
        feed = original(**kwargs)
        created.append(feed)
        return feed

    monkeypatch.setattr(PrestreamFeedFactory, "create", capture)
    node = build_shell(plan(), arm_id="fixture-a", strategies=())
    try:
        assert len(created) == 1
        with pytest.raises(RuntimeError, match="disabled"):
            asyncio.run(created[0]._connect())
    finally:
        node.dispose()


def snapshot_file(tmp_path, *, quote_at="2026-10-27T08:49:37+00:00", bid="10.01"):
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "as_of": "2026-10-27T08:49:38+00:00",
                "generated_at": "2026-10-27T08:49:39+00:00",
                "symbols": [
                    {
                        "symbol": "AAA",
                        "rank": 1,
                        "coverage": {
                            "tradeability": {"bid": bid, "ask": "10.02", "quote_at": quote_at}
                        },
                    }
                ],
            }
        )
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_recorded_quote_uses_generation_clock_without_inventing_a_receipt(tmp_path):
    path, digest = snapshot_file(tmp_path)
    result = read_snapshot(path, expected_sha256=digest, symbols=frozenset({"AAA"}))
    (quote,) = result.quotes
    assert quote.bid_price.as_decimal() == Decimal("10.01")
    assert quote.ts_event < quote.ts_init == result.generated_ns
    assert result.sha256 == digest
    assert result.capture_completed_ns is result.received_ns is None
    assert result.ranking_authority == "UNAVAILABLE"
    assert result.tier == "MODELED"
    with pytest.raises(ValueError, match="sizes"):
        quote.to_native()


@pytest.mark.parametrize(
    "quote_at,bid",
    [
        ("2026-10-27T08:49:40+00:00", "10.01"),
        ("2026-10-27T08:49:37+00:00", "NaN"),
    ],
)
def test_snapshot_refuses_future_or_invalid_quotes(tmp_path, quote_at, bid):
    path, digest = snapshot_file(tmp_path, quote_at=quote_at, bid=bid)
    with pytest.raises(ValueError):
        read_snapshot(path, expected_sha256=digest, symbols=frozenset({"AAA"}))


def test_snapshot_refuses_hash_tampering_before_loading_prices(tmp_path):
    path, digest = snapshot_file(tmp_path)
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        read_snapshot(path, expected_sha256=digest, symbols=frozenset({"AAA"}))
