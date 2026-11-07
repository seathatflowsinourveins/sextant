"""Offline native configs from one canonical paper account; no readiness receipt.

Sources: NautilusTrader v2.0.0rc8 (d53849b216e20f2c122ca01b4dd0da377638b186),
config bindings and common/{symbology,spreads}.rs; data-policy authority: lanes/paper/ibkr.toml.
northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:src/northstar_trading/nodes/ibkr.py,
_paper_account, require_us_equity, and ibkr_paper_spec's provider/client configuration.

Only config objects are built; custody, wire pacing and handover still need qualification (#81).
"""

import re
from dataclasses import dataclass

from nautilus_trader.adapters.interactive_brokers import (
    InteractiveBrokersDataClientConfig,
    InteractiveBrokersExecutionClientConfig,
    InteractiveBrokersInstrumentProviderConfig,
    MarketDataType,
    SymbologyMethod,
)
from nautilus_trader.model import InstrumentId

from sextant.paper.config import PaperAccount

US_EQUITY_VENUES = frozenset({"NASDAQ", "NYSE", "ARCA", "AMEX", "BATS", "IEX"})
_UNSUPPORTED = re.compile(r"[=^()]|___|\d{6}[CP]\d{8}$")


@dataclass(frozen=True)
class IbkrClientConfigs:
    data: InteractiveBrokersDataClientConfig
    execution: InteractiveBrokersExecutionClientConfig


def build_client_configs(
    *,
    account: PaperAccount,
    host: str,
    data_client_id: int,
    exec_client_id: int,
    load_ids: frozenset[InstrumentId],
    connection_timeout: int,
    request_timeout: int,
    use_regular_trading_hours: bool,
    ignore_quote_tick_size_updates: bool,
    batch_quotes: bool,
    market_data_type: MarketDataType,
) -> IbkrClientConfigs:
    """Build native configs from explicit inputs; never resolve or contact their endpoint.

    Account identity, timeouts and the complete deployed/held/retained preload set belong to the
    caller. No cached default or environment fallback supplies authority. Identifier checks carry
    the source's narrow US-equity scope; they do not establish a qualified contract, current price,
    execution-provider readiness or custody. In particular, the sub-$1 refusal must still occur
    at actual send in the shared node.
    """
    if not isinstance(account, PaperAccount) or account.lane != "ibkr-paper":
        raise ValueError("IBKR requires the shared IBKR paper account")
    if account.ib_port is None:
        raise ValueError("IBKR paper account requires its validated port")
    if data_client_id == exec_client_id:
        raise ValueError("IBKR data and execution client identities must be distinct")
    load_ids = frozenset(load_ids)
    for iid in load_ids:
        if iid.venue.value not in US_EQUITY_VENUES or _UNSUPPORTED.search(iid.symbol.value):
            raise ValueError(f"{iid}: only US equities are configurable")

    provider = InteractiveBrokersInstrumentProviderConfig(
        symbology_method=SymbologyMethod.SIMPLIFIED, load_ids=set(load_ids)
    )
    return IbkrClientConfigs(
        data=InteractiveBrokersDataClientConfig(
            host=host,
            port=account.ib_port,
            client_id=data_client_id,
            use_regular_trading_hours=use_regular_trading_hours,
            batch_quotes=batch_quotes,
            ignore_quote_tick_size_updates=ignore_quote_tick_size_updates,
            market_data_type=market_data_type,
            instrument_provider=provider,
            connection_timeout=connection_timeout,
            request_timeout=request_timeout,
        ),
        execution=InteractiveBrokersExecutionClientConfig(
            host=host,
            port=account.ib_port,
            client_id=exec_client_id,
            account_id=account.account_id,
            instrument_provider=provider,
            connection_timeout=connection_timeout,
            request_timeout=request_timeout,
        ),
    )
