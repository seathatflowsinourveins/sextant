"""Paper-only Alpaca transport: status mapping and one wire call, with no network."""

from typing import Any
from urllib.parse import urlsplit

import pytest
import requests

from sextant.execution.alpaca import Outcome, WireRequest
from sextant.execution.alpaca_transport import PAPER_HOST, build_transport
from sextant.execution.pacer import ActionKind

ORDER_BODY = {
    "client_order_id": "house-exit",
    "symbol": "AAA",
    "side": "sell",
    "qty": "100",
    "type": "limit",
    "time_in_force": "day",
    "order_class": "simple",
    "limit_price": "10.01",
    "extended_hours": False,
}
CREDENTIALS = ("fixture-key", "fixture-secret")


def wire_request() -> WireRequest:
    return WireRequest(
        "POST",
        "/v2/orders",
        ORDER_BODY,
        "house-exit",
        ActionKind.SUBMIT,
        0,
        1,
        "lease-token",
        "params-hash",
    )


def query_request() -> WireRequest:
    return WireRequest(
        "GET", "/v2/positions", {}, None, ActionKind.QUERY, 0, 0, "lease-token", "params-hash"
    )


def request_with_path(path: str) -> WireRequest:
    return WireRequest(
        "POST",
        path,
        ORDER_BODY,
        "house-exit",
        ActionKind.SUBMIT,
        0,
        1,
        "lease-token",
        "params-hash",
    )


class FakeResponse:
    def __init__(self, status_code: int, payload: object = None):
        self.status_code, self.payload = status_code, payload

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("empty response body")
        return self.payload


class FakeSession:
    """Records the single request a transport is allowed to make; opens no socket."""

    def __init__(self, result: FakeResponse | Exception, *, wire_calls: list[int] | None = None):
        self.result = result
        self.wire_calls = wire_calls
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        if self.wire_calls is not None:
            assert len(self.wire_calls) == 1, "wire() must run once immediately before the request"
        self.calls.append((method, url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def build(session: FakeSession, **kwargs: Any):
    return build_transport(
        key=CREDENTIALS[0],
        secret=CREDENTIALS[1],
        session=session,
        **kwargs,
    )


def send(
    session: FakeSession,
    *,
    request: WireRequest | None = None,
    base_url: str = PAPER_HOST,
    timeout_s: float = 10.0,
) -> tuple[Outcome, list[int]]:
    wire_calls: list[int] = []
    session.wire_calls = wire_calls
    outbound = wire_request() if request is None else request
    outcome = build(session, base_url=base_url, timeout_s=timeout_s)(
        outbound, lambda: wire_calls.append(1)
    )
    return outcome, wire_calls


def test_200_ack_carries_the_venue_id_and_sends_one_wire_and_one_request():
    wire_calls: list[int] = []
    session = FakeSession(FakeResponse(200, {"id": "venue-1"}), wire_calls=wire_calls)

    outcome = build(session)(wire_request(), lambda: wire_calls.append(1))

    assert outcome == Outcome("ACK", "venue-1")
    assert wire_calls == [1]
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == f"{PAPER_HOST}/v2/orders"
    assert kwargs["headers"] == {
        "APCA-API-KEY-ID": CREDENTIALS[0],
        "APCA-API-SECRET-KEY": CREDENTIALS[1],
        "Content-Type": "application/json",
    }
    assert isinstance(kwargs["json"], dict)
    assert kwargs["json"] == ORDER_BODY
    assert kwargs["timeout"] == 10.0
    assert kwargs["allow_redirects"] is False


def test_201_ack_behaves_like_200():
    session = FakeSession(FakeResponse(201, {"id": "venue-2"}))

    outcome, wire_calls = send(session)

    assert outcome == Outcome("ACK", "venue-2")
    assert wire_calls == [1]
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(FakeResponse(200, {}), id="no-id-field"),
        pytest.param(FakeResponse(201, {"id": ""}), id="empty-id"),
        pytest.param(FakeResponse(200, {"id": 7}), id="non-string-id"),
        pytest.param(FakeResponse(204, None), id="no-body"),
    ],
)
def test_a_2xx_without_a_usable_id_is_unknown(response):
    session = FakeSession(response)

    outcome, wire_calls = send(session)

    assert outcome == Outcome("UNKNOWN")
    assert wire_calls == [1]
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, "REFUSED"),
        (422, "REFUSED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMIT"),
        (500, "UNKNOWN"),
        (503, "UNKNOWN"),
    ],
)
def test_http_status_maps_to_an_outcome_with_no_retry(status, kind):
    session = FakeSession(FakeResponse(status, {"message": "venue answer"}))

    outcome, wire_calls = send(session)

    assert outcome == Outcome(kind)
    assert wire_calls == [1]
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("slow"),
        requests.ConnectionError("refused"),
        requests.HTTPError("server answer"),
    ],
    ids=["timeout", "connection", "http-error"],
)
def test_transport_errors_are_unknown_after_exactly_one_wire(error):
    session = FakeSession(error)

    outcome, wire_calls = send(session)

    assert outcome == Outcome("UNKNOWN")
    assert wire_calls == [1]
    assert len(session.calls) == 1


def test_a_redirect_is_not_followed_and_maps_to_unknown():
    session = FakeSession(FakeResponse(302, {"message": "moved"}))

    outcome, wire_calls = send(session)

    assert outcome == Outcome("UNKNOWN")
    assert wire_calls == [1]
    assert len(session.calls) == 1
    assert session.calls[0][2]["allow_redirects"] is False


@pytest.mark.parametrize(
    "payload",
    [[], [{"symbol": "AAA", "qty": "100"}], {"account_number": "acct-1"}],
    ids=["empty-list", "list", "mapping"],
)
def test_a_query_2xx_decodable_body_is_an_ack_without_a_venue_id(payload):
    session = FakeSession(FakeResponse(200, payload))

    outcome, wire_calls = send(session, request=query_request())

    assert outcome == Outcome("ACK")
    assert wire_calls == [1]
    assert len(session.calls) == 1


def test_a_normal_root_relative_path_passes_and_keeps_the_paper_host():
    session = FakeSession(FakeResponse(200, {"id": "venue-1"}))

    outcome, wire_calls = send(session)

    assert outcome == Outcome("ACK", "venue-1")
    assert wire_calls == [1]
    assert session.calls[0][1] == f"{PAPER_HOST}/v2/orders"
    assert urlsplit(session.calls[0][1]).hostname == "paper-api.alpaca.markets"


@pytest.mark.parametrize(
    "path",
    [
        "@api.alpaca.markets/v2/orders",
        "//api.alpaca.markets/v2/orders",
        "https://api.alpaca.markets/v2/orders",
        "/v2/orders@",
        "/v2/orders\\",
    ],
    ids=["userinfo", "scheme-relative", "absolute-url", "trailing-at", "backslash"],
)
def test_a_path_that_could_retarget_the_request_is_refused_without_wire(path):
    wire_calls: list[int] = []
    session = FakeSession(FakeResponse(200, {"id": "venue-1"}), wire_calls=wire_calls)

    with pytest.raises(ValueError):
        build(session)(request_with_path(path), lambda: wire_calls.append(1))

    assert wire_calls == []
    assert session.calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.com",
        "http://paper-api.alpaca.markets",
        PAPER_HOST + "/",
        PAPER_HOST + "/v2",
        PAPER_HOST + "?paper=false",
        "https://paper-api.alpaca.markets:443",
    ],
    ids=["other-host", "http", "trailing-slash", "path", "query", "port"],
)
def test_build_refuses_anything_but_the_paper_root(base_url):
    with pytest.raises(ValueError, match="paper-only"):
        build_transport(key=CREDENTIALS[0], secret=CREDENTIALS[1], base_url=base_url)


def test_build_accepts_the_paper_root_and_nothing_else():
    session = FakeSession(FakeResponse(200, {"id": "venue-3"}))

    transport = build_transport(key=CREDENTIALS[0], secret=CREDENTIALS[1], session=session)

    assert callable(transport)
    for base_url in ("https://example.com", "http://paper-api.alpaca.markets"):
        with pytest.raises(ValueError, match="paper-only"):
            build_transport(
                key=CREDENTIALS[0],
                secret=CREDENTIALS[1],
                base_url=base_url,
                session=FakeSession(FakeResponse(200)),
            )


@pytest.mark.parametrize(
    ("key", "secret"),
    [("", CREDENTIALS[1]), (CREDENTIALS[0], "")],
    ids=["empty-key", "empty-secret"],
)
def test_build_refuses_empty_credentials(key, secret):
    with pytest.raises(ValueError):
        build_transport(key=key, secret=secret, session=FakeSession(FakeResponse(200)))


def test_a_wire_that_raises_aborts_before_any_request():
    session = FakeSession(FakeResponse(200, {"id": "venue-1"}))

    def abort() -> None:
        raise RuntimeError("admission changed")

    with pytest.raises(RuntimeError):
        build(session)(wire_request(), abort)
    assert session.calls == []


def test_build_errors_never_echo_the_credentials():
    with pytest.raises(ValueError) as error:
        build_transport(
            key=CREDENTIALS[0],
            secret=CREDENTIALS[1],
            base_url="https://example.com",
            session=FakeSession(FakeResponse(200)),
        )

    message = str(error.value)
    assert CREDENTIALS[0] not in message
    assert CREDENTIALS[1] not in message
