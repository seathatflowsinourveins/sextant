"""Wire B's protector to alpaca-py's trading client and trade-update stream.

The wiring follows the alpaca-py v0.44.0 notebook
``examples/stocks/stocks-trading-basic.ipynb`` cells 25-36: build ``TradingClient(paper=True)``
and ``TradingStream(paper=True)``, subscribe the trade-updates handler, then run the stream.
``ProtectorStream`` supplies the reconnect reconcile; this module only reads the slot-2
config, checks the broker account, installs a clean SIGTERM stop, and runs.

The config is a JSON object with ``PaperAccount``'s fields: ``lane``, ``account_id``,
``client_id``, ``namespace`` and ``sessions``. It is supplied with ``--config`` and is never
committed with an account number. Keys and the expected account come only from the
environment: ``with-keys`` exports ``ALPACA_PAPER_2_API_KEY`` and
``ALPACA_PAPER_2_SECRET_KEY``; ``B_EXPECTED_ACCOUNT_SUFFIX`` (or the optional full
``B_EXPECTED_ACCOUNT_ID``, which wins over the suffix) bounds the fetched account number.
The fetched number is compared and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import Any, cast

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.client import TradingClient

from sextant.execution.custody import AccountScope, WriterLease
from sextant.execution.pacer import AccountPacer, ActionKind, PacerRefused
from sextant.paper.b_feed import LatestDataClient
from sextant.paper.b_protector import (
    BParameters,
    Page,
    ProtectorRefusal,
    ProtectorStream,
    TradingClientLike,
    load_b_parameters,
)
from sextant.paper.config import PaperAccount, PaperBudget, load_budget
from sextant.paper.sessions import Session
from sextant.risk.controls import Controls

DEFAULT_PARAMETERS = Path(__file__).resolve().parents[3] / "lanes/paper/b-parameters.json"
DEFAULT_LIMITS = Path(__file__).resolve().parents[3] / "lanes/limits.yaml"
CONFIG_KEYS = frozenset({"lane", "account_id", "client_id", "namespace", "sessions"})
KEY_NAMES = ("ALPACA_PAPER_2_API_KEY", "ALPACA_PAPER_2_SECRET_KEY")
EXPECTED_SUFFIX_ENV = "B_EXPECTED_ACCOUNT_SUFFIX"
EXPECTED_FULL_ENV = "B_EXPECTED_ACCOUNT_ID"
DEFAULT_CLIENT_FACTORY: Callable[..., TradingClientLike] = cast(
    Callable[..., TradingClientLike], TradingClient
)
DEFAULT_DATA_CLIENT_FACTORY: Callable[..., LatestDataClient] = cast(
    Callable[..., LatestDataClient], StockHistoricalDataClient
)


class PacedTradingClient:
    """Route every broker read and write through the repo's existing account pacer."""

    def __init__(self, client: TradingClientLike, pacer: Any) -> None:
        self._client = client
        self._pacer = pacer

    def _call(self, kind: ActionKind, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        results: list[Any] = []
        state = {"cancelled": False}

        def send(before_wire: Callable[[], None]) -> None:
            before_wire()
            results.append(method(*args, **kwargs))

        def admission() -> bool:
            return not state["cancelled"]

        self._pacer.request(kind, send, admission=admission)
        if not results:
            raise PacerRefused(f"the account pacer did not admit {method.__name__}")
        return results[0]

    def get_account(self) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_account)

    def get_all_positions(self) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_all_positions)

    def get_orders(self, filter: Any = None) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_orders, filter)

    def get_order_by_client_id(self, client_id: str) -> Any:
        return self._call(ActionKind.QUERY, self._client.get_order_by_client_id, client_id)

    def submit_order(self, order_data: Any) -> Any:
        return self._call(ActionKind.REDUCE, self._client.submit_order, order_data)

    def cancel_order_by_id(self, order_id: object) -> None:
        self._call(ActionKind.CANCEL, self._client.cancel_order_by_id, order_id)


class BudgetControls:
    """The row-8 controls AccountPacer needs, from the existing paper budget row."""

    def __init__(self, budget: PaperBudget) -> None:
        self._values: dict[str, Any] = {
            "request_budget": budget.requests,
            "window_s": Decimal(budget.window_s),
            "burst": max(1, budget.requests // 10),
        }

    def __getitem__(self, name: str) -> Any:
        return self._values[name]

    def ns(self, name: str) -> int:
        return int(self._values[name] * Decimal(1_000_000_000))

    @property
    def burst(self) -> int:
        return int(self._values["burst"])


def load_account_config(path: Path) -> PaperAccount:
    """Read the slot-2 account config and let PaperAccount validate it."""

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}") from exc
    if not isinstance(data, dict) or set(data) != CONFIG_KEYS:
        raise ValueError("B account config has the wrong keys")
    for key in ("lane", "account_id", "client_id", "namespace"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f"B account config needs a nonempty {key}")
    sessions = data["sessions"]
    if (
        not isinstance(sessions, list)
        or not sessions
        or any(not isinstance(name, str) for name in sessions)
    ):
        raise ValueError("B account config needs a nonempty sessions list")
    try:
        parsed_sessions = tuple(Session[name.upper()] for name in sessions)
    except KeyError as exc:
        raise ValueError(f"B account config has an unknown session: {exc.args[0]}") from exc
    return PaperAccount(
        lane=data["lane"],
        account_id=data["account_id"],
        client_id=data["client_id"],
        namespace=data["namespace"],
        sessions=parsed_sessions,
    )


def _print_page(page: Page) -> None:
    symbol = f" {page.symbol}" if page.symbol else ""
    detail = f" ({page.detail})" if page.detail else ""
    print(f"page {page.reason}{symbol}{detail}", flush=True)


def _print_state(line: str) -> None:
    print(line, flush=True)


def _check_expected_account(client: TradingClientLike, on_page: Callable[[Page], None]) -> None:
    """Compare the fetched account number to the local expectation; never print it."""

    suffix = os.environ.get(EXPECTED_SUFFIX_ENV) or ""
    full = os.environ.get(EXPECTED_FULL_ENV) or ""
    if not suffix and not full:
        raise SystemExit(f"{EXPECTED_SUFFIX_ENV} or {EXPECTED_FULL_ENV} must be set")
    number = client.get_account().account_number
    matched = number == full if full else number.endswith(suffix)
    if not matched:
        on_page(Page(reason="account_number_mismatch"))
        raise ProtectorRefusal(
            "the broker account number does not match the expected B paper account"
        )


def _sigterm_handler(stream: ProtectorStream) -> Callable[[int, FrameType | None], None]:
    """Stop the stream from its own loop; the resting broker trail is left in place."""

    def stop(signum: int, frame: FrameType | None) -> None:
        loop = getattr(stream, "_loop", None)
        if loop is None or not loop.is_running():
            raise SystemExit(0)
        loop.call_soon_threadsafe(lambda: loop.create_task(stream.stop_ws()))

    return stop


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., TradingClientLike] = DEFAULT_CLIENT_FACTORY,
    on_page: Callable[[Page], None] = _print_page,
    on_state: Callable[[str], None] = _print_state,
    data_client_factory: Callable[..., LatestDataClient] = DEFAULT_DATA_CLIENT_FACTORY,
) -> int:
    """Read the slot-2 config and keys, then run the protector stream in the foreground."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="slot-2 PaperAccount JSON")
    parser.add_argument(
        "--parameters",
        type=Path,
        default=DEFAULT_PARAMETERS,
        help="B's UNCALIBRATED registry rows",
    )
    parser.add_argument(
        "--limits",
        type=Path,
        default=DEFAULT_LIMITS,
        help="shared paper rate-limit rows",
    )
    parser.add_argument(
        "--lease-root",
        type=Path,
        default=None,
        help="account writer lease directory (default: <config dir>/locks)",
    )
    args = parser.parse_args(argv)

    account = load_account_config(args.config)
    parameters: BParameters = load_b_parameters(args.parameters)
    budget = load_budget(args.limits, account.lane)
    lease_root = args.lease_root or args.config.parent / "locks"
    lease = WriterLease(AccountScope(account.broker, account.account_id), lease_root, "b-protector")
    lease.acquire()
    try:
        api_key = os.environ.get(KEY_NAMES[0])
        secret_key = os.environ.get(KEY_NAMES[1])
        if not api_key or not secret_key:
            raise SystemExit(f"{KEY_NAMES[0]} and {KEY_NAMES[1]} must be set by with-keys")

        pacer = AccountPacer(cast(Controls, BudgetControls(budget)), now_ns=time.time_ns)
        lease.bind_pacer(pacer)
        client = PacedTradingClient(
            client_factory(api_key=api_key, secret_key=secret_key, paper=True),
            pacer,
        )
        try:
            data_client: LatestDataClient | None = data_client_factory(
                api_key=api_key, secret_key=secret_key
            )
        except Exception as exc:
            on_page(Page(reason="feed_client_failed", detail=type(exc).__name__))
            data_client = None
        stream = ProtectorStream(
            client,
            account,
            parameters,
            api_key=api_key,
            secret_key=secret_key,
            paper=True,
            on_page=on_page,
            on_state=on_state,
            data_client=data_client,
        )
        _check_expected_account(client, on_page)
        previous = signal.signal(signal.SIGTERM, _sigterm_handler(stream))
        try:
            stream.run()
        finally:
            signal.signal(signal.SIGTERM, previous)
    finally:
        lease.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
