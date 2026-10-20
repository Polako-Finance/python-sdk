"""Every public payment method of the client against a fake gateway."""

import asyncio
import logging
import random
import ssl
import sys
import warnings
from typing import Optional
from uuid import uuid4

import anyio
import httpcore
import httpx
import pytest

import polako.sdk as sdk
from polako.sdk import (
    ConfigurationError,
    HttpClientError,
    HttpRequestError,
    InvalidArgumentError,
    InvalidHeaderValueError,
    PolakoClient,
)
from polako.sdk._async_client import (
    _CUT_CONNECTION_REASONS,
    _DAMAGED_RECORD_REASONS,
    AsyncHttpClient,
    _is_sdk_module,
)
from polako.sdk._constants import REFUND_REASON_MAX_LENGTH, REFUND_REASON_MIN_LENGTH
from tests.factories import (
    make_customer_info,
    make_idempotency_key,
    make_init_customer_info,
    make_order_details,
    make_order_status_response,
    make_payment_url_response,
    make_refund_item,
    make_refund_response,
    make_session_details_response,
    make_session_info_response,
    make_subscribe_args,
    make_subscribe_response,
    make_success_step,
    sign,
)
from tests.generators import (
    WAIT_LIMIT_SECONDS,
    generate_random_host,
    generate_readable_string,
    generate_short_timeout,
)


def keyed() -> dict:
    return {"Idempotency-Key": make_idempotency_key()}


def any_path() -> str:
    return f"/v1/{generate_readable_string(6)}"


def any_body() -> dict:
    return {generate_readable_string(6): generate_readable_string(6)}


@pytest.mark.asyncio
async def test_create_order(client, gateway, platform):
    order = make_order_details(currency=None, language=None)
    response = make_session_info_response()
    gateway.respond(body=response)

    async with client:
        session = await client.create_order(order, make_customer_info(), platform.platform_id, platform.secret_key)

    assert session.paymentSessionId == response["paymentSessionId"]
    assert session.paymentPageUrl == response["paymentPageUrl"]
    assert gateway.last.method == "POST"
    assert gateway.last.url.host == "stg-api.infra.polako-finance.com"  # the real host, not a constant of the SDK
    assert gateway.last.url.path == "/v1/session/signed"
    body = gateway.last_json()
    assert body["platform_id"] == str(platform.platform_id)
    assert body["order_id"] == order.order_id
    assert body["currency"] == "RSD"
    assert body["language"] == "sr"
    assert body["total"] == f"{order.total:.2f}"
    assert body["signature"] == sign(f"{order.order_id}|{order.total:.2f}|RSD", platform.secret_key)


@pytest.mark.asyncio
async def test_create_order_validates_before_sending(client, gateway, platform):
    order = make_order_details()
    order.items = []

    async with client:
        with pytest.raises(ValueError):
            await client.create_order(order, make_customer_info(), platform.platform_id, platform.secret_key)

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_production_base_url_by_default(gateway, platform):
    gateway.respond(body=make_session_info_response())

    async with PolakoClient() as prod:
        await prod.create_order(make_order_details(), make_customer_info(), platform.platform_id, platform.secret_key)

    assert gateway.last.url.host == "api.infra.polako-finance.com"  # the real host, not a constant of the SDK


@pytest.mark.asyncio
async def test_get_session_details(client, gateway):
    response = make_session_details_response()
    gateway.respond(body=response)

    async with client:
        details = await client.get_session_details(response["session_id"])

    assert details.session_id == response["session_id"]
    assert details.shopping_cart.items[0].name == response["shopping_cart"]["items"][0]["name"]
    assert details.payment_options[0].id == response["payment_options"][0]["id"]
    assert gateway.last.method == "GET"
    assert gateway.last.url.path == f"/v1/session/{response['session_id']}"


@pytest.mark.asyncio
async def test_get_payment_url(client, gateway):
    session_id, option_id = uuid4(), uuid4()
    response = make_payment_url_response(sessionId=str(session_id))
    gateway.respond(body=response)
    customer = make_init_customer_info()

    async with client:
        result = await client.get_payment_url(session_id, option_id, customer, "en", True)

    assert result.paymentUrl == response["paymentUrl"]
    assert gateway.last.url.path == f"/v1/session/{session_id}/payment_url"
    body = gateway.last_json()
    assert body["payment_option_id"] == str(option_id)
    assert body["terms_accepted"] is True
    assert body["customer"]["email"] == customer.email


@pytest.mark.asyncio
async def test_check_order_status(client, gateway, platform):
    session_id = uuid4()
    response = make_order_status_response(session_id=str(session_id))
    gateway.respond(body=response)

    async with client:
        status = await client.check_order_status(session_id, platform.platform_id, platform.secret_key)

    assert status.status == response["status"]
    assert gateway.last.url.path == f"/v1/session/{session_id}/status/signed"
    assert gateway.last_json()["signature"] == sign(f"status|{session_id}|{platform.platform_id}", platform.secret_key)


@pytest.mark.asyncio
async def test_refund_full_and_partial(client, gateway, platform):
    session_id = uuid4()
    response = make_refund_response(session_id=str(session_id), session_status="REFUNDED")
    gateway.respond(body=response)
    reason = generate_readable_string(20)
    item = make_refund_item()

    async with client:
        refund = await client.refund_session(session_id, platform.platform_id, platform.secret_key, reason)
        assert refund.session_status == "REFUNDED"
        assert gateway.last.url.path == f"/v1/session/{session_id}/refund/signed"
        assert gateway.last_json()["is_full_refund"] is True
        assert gateway.last_json()["reason"] == reason

        await client.refund_session(session_id, platform.platform_id, platform.secret_key, reason, [item])
        body = gateway.last_json()
        assert body["is_full_refund"] is False
        assert body["refund_items"] == [
            {"item_id": item.item_id, "refund_quantity": item.refund_quantity, "item_code": item.item_code}
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason, items",
    [
        (generate_readable_string(REFUND_REASON_MIN_LENGTH - 1), None),
        (generate_readable_string(REFUND_REASON_MAX_LENGTH + 1), None),
        (generate_readable_string(20), []),
    ],
)
async def test_refund_argument_validation(client, gateway, platform, reason, items):
    async with client:
        with pytest.raises(ValueError):
            await client.refund_session(uuid4(), platform.platform_id, platform.secret_key, reason, items)

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_http_error_carries_status_and_body(client, gateway):
    detail = generate_readable_string(12)
    gateway.respond(status=410, text=f'{{"detail": "{detail}"}}')

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.status_code == 410
    assert detail in exc.value.response_body


@pytest.mark.asyncio
async def test_malformed_success_body_is_request_error(client, gateway):
    gateway.respond(text=generate_readable_string(12))

    async with client:
        with pytest.raises(HttpRequestError):
            await client.get_session_details(uuid4())


@pytest.mark.asyncio
async def test_network_error_is_client_error_not_request_error(client, gateway):
    text = generate_readable_string(12)
    error = httpx.ConnectError(text)
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert not isinstance(exc.value, HttpRequestError)
    assert exc.value.message == f"Request failed: ConnectError: {text}"
    assert exc.value.__cause__ is error


@pytest.mark.asyncio
async def test_network_error_message_names_the_failure_when_httpx_gives_no_text(client, gateway):
    # httpx raises the timeouts and a reset connection with an empty text: the message must still say what
    # happened, not end after the colon.
    error = httpx.ReadTimeout("")
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == "Request failed: ReadTimeout"
    assert exc.value.__cause__ is error


@pytest.mark.asyncio
async def test_works_without_context_manager(client, gateway, platform):
    response = make_order_status_response()
    gateway.respond(body=response)

    status = await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert status.status == response["status"]


@pytest.mark.asyncio
async def test_a_failure_with_no_text_shows_the_reason_found_deeper_on_the_error_chain(client, gateway):
    # httpcore re-raises a cut handshake or a reset connection from None: the readable reason is only the context.
    reason = generate_readable_string(12)
    error = httpx.ConnectError("")
    error.__context__ = ConnectionResetError(reason)
    error.__suppress_context__ = True  # what `raise ... from None` does
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == f"Request failed: ConnectError: ConnectionResetError: {reason}"


@pytest.mark.asyncio
async def test_an_unexpected_failure_is_described_by_its_class_and_text(client, gateway):
    text = generate_readable_string(12)
    gateway.fail(TypeError(text))

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == f"Unexpected error during request: TypeError: {text}"


@pytest.mark.asyncio
async def test_an_unexpected_failure_with_no_text_does_not_borrow_the_text_of_an_unrelated_error(client, gateway):
    error = TypeError("")
    error.__context__ = OSError(generate_readable_string(12))
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == "Unexpected error during request: TypeError"


def tls_error(reason: Optional[str], text: str) -> ssl.SSLError:
    """An ssl.SSLError the way OpenSSL raises it: the code is in `reason` and in the text (none for a code that the
    running Python does not know)."""
    error = ssl.SSLError(f"[SSL: {reason}] {text}" if reason else text)
    error.reason = reason  # type: ignore[attr-defined]
    return error


# The reason codes of TLS errors that a test pins. DAMAGED_RECORD_REASONS is written out here on purpose and compared
# with the SDK's constant, so a reason cannot be added to or taken from the SDK's list without a decision here.
# PERMANENT_TLS_REASONS are failures of the setup that a repeat does not cure; no test may find them on the SDK's list.
DAMAGED_RECORD_REASONS = [
    "DECRYPTION_FAILED_OR_BAD_RECORD_MAC",
    "DECRYPTION_FAILED",
    "BAD_RECORD_MAC",
    "SSLV3_ALERT_BAD_RECORD_MAC",
    "RECORD_LAYER_FAILURE",
    "UNEXPECTED_RECORD",
    "BAD_LENGTH",
    "PACKET_LENGTH_TOO_LONG",
    "APPLICATION_DATA_AFTER_CLOSE_NOTIFY",
]
# A plain SSLError that carries it is a cut connection (CPython raises it as SSLEOFError); compared with the SDK too.
CUT_CONNECTION_REASONS = ["UNEXPECTED_EOF_WHILE_READING"]
PERMANENT_TLS_REASONS = [
    "CERTIFICATE_VERIFY_FAILED",
    "WRONG_VERSION_NUMBER",
    "TLSV1_ALERT_PROTOCOL_VERSION",
    "UNSUPPORTED_PROTOCOL",
    "SSLV3_ALERT_HANDSHAKE_FAILURE",
    "BAD_DH_VALUE",
    "NO_SHARED_CIPHER",
    "NO_CERTIFICATE_OR_CRL_FOUND",
    "EE_KEY_TOO_SMALL",
    "TLSV1_ALERT_INTERNAL_ERROR",
    # Under TLS 1.3 the client's handshake is over before the server judges its last flight, so these two alerts can be
    # a deterministic rejection that arrives unwrapped on the first read.
    "SSLV3_ALERT_UNEXPECTED_MESSAGE",
    "TLSV1_ALERT_DECODE_ERROR",
]


def test_the_damaged_record_reasons_of_the_sdk_are_the_ones_the_tests_name():
    assert set(DAMAGED_RECORD_REASONS) == set(_DAMAGED_RECORD_REASONS)
    assert len(DAMAGED_RECORD_REASONS) == len(set(DAMAGED_RECORD_REASONS))


def test_the_cut_connection_reasons_of_the_sdk_are_the_ones_the_tests_name():
    assert set(CUT_CONNECTION_REASONS) == set(_CUT_CONNECTION_REASONS)


def test_no_permanent_reason_is_on_the_lists_of_the_sdk():
    assert not set(PERMANENT_TLS_REASONS) & (set(_DAMAGED_RECORD_REASONS) | set(_CUT_CONNECTION_REASONS))


CUT_CONNECTION_CLASSES = [ssl.SSLEOFError, ssl.SSLZeroReturnError, ssl.SSLSyscallError]
OS_TRANSIENT_CLASSES = [ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError, BrokenPipeError, TimeoutError]
OS_PERMANENT_CLASSES = [FileNotFoundError, PermissionError]
# What anyio raises for a cut stream; some httpcore versions may let these through unmapped (not checked per version).
CUT_STREAM_CLASSES = [anyio.EndOfStream, anyio.BrokenResourceError]


# An error as it reaches the SDK from an established connection or from the system, nothing around it.
UNWRAPPED_TRANSIENT = (
    [pytest.param(lambda text, c=c: c(text), id=c.__name__) for c in CUT_CONNECTION_CLASSES + OS_TRANSIENT_CLASSES]
    + [pytest.param(lambda text, c=c: c(text), id=f"anyio-{c.__name__}") for c in CUT_STREAM_CLASSES]
    + [pytest.param(lambda text, r=r: tls_error(r, text), id=r) for r in DAMAGED_RECORD_REASONS + CUT_CONNECTION_REASONS]
)
UNWRAPPED_PERMANENT = (
    [pytest.param(lambda text: ssl.SSLCertVerificationError(text), id="SSLCertVerificationError")]
    + [pytest.param(lambda text, r=r: tls_error(r, text), id=r) for r in PERMANENT_TLS_REASONS]
    + [pytest.param(lambda text: tls_error(generate_readable_string(10).upper(), text), id="made-up-reason")]
    + [pytest.param(lambda text: tls_error(None, text), id="no-reason")]
    + [pytest.param(lambda text, c=c: c(text), id=c.__name__) for c in OS_PERMANENT_CLASSES]
)


def wrapped_by_httpx(make_cause):
    """The shape httpx really gives while connecting: httpx.ConnectError, caused by httpcore.ConnectError, which holds
    the original error as the context that `raise ... from None` suppressed."""

    def make(text):
        inner = httpcore.ConnectError(generate_readable_string(8))
        inner.__context__ = make_cause(text)
        inner.__suppress_context__ = True
        outer = httpx.ConnectError(generate_readable_string(8))
        outer.__cause__ = inner
        return outer

    return make


# The same errors while connecting (the handshake): only a cut connection is cured by a repeat.
CONNECT_TRANSIENT = [
    pytest.param(wrapped_by_httpx(lambda text, c=c: c(text)), id=f"connect-{c.__name__}")
    for c in CUT_CONNECTION_CLASSES + OS_TRANSIENT_CLASSES
] + [pytest.param(wrapped_by_httpx(lambda text, r=r: tls_error(r, text)), id=f"connect-{r}") for r in CUT_CONNECTION_REASONS]
CONNECT_PERMANENT = (
    [pytest.param(wrapped_by_httpx(lambda text: ssl.SSLCertVerificationError(text)), id="connect-SSLCertVerificationError")]
    + [pytest.param(wrapped_by_httpx(lambda text, r=r: tls_error(r, text)), id=f"connect-{r}") for r in PERMANENT_TLS_REASONS]
    + [pytest.param(wrapped_by_httpx(lambda text, r=r: tls_error(r, text)), id=f"connect-{r}") for r in DAMAGED_RECORD_REASONS]
    + [pytest.param(wrapped_by_httpx(lambda text: tls_error(None, text)), id="connect-no-reason")]
)


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", UNWRAPPED_TRANSIENT + UNWRAPPED_PERMANENT + CONNECT_TRANSIENT + CONNECT_PERMANENT)
async def test_a_failure_before_an_answer_is_a_client_error_not_a_gateway_answer(client, gateway, make_error):
    error = make_error(generate_readable_string(12))
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert not isinstance(exc.value, HttpRequestError)
    assert exc.value.__cause__ is error


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", UNWRAPPED_TRANSIENT + CONNECT_TRANSIENT)
async def test_a_transient_failure_is_retried_when_the_request_is_keyed(gateway, sleeps, make_error):
    gateway.sequence(make_error(generate_readable_string(12)), make_success_step())

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", UNWRAPPED_PERMANENT + CONNECT_PERMANENT)
async def test_a_permanent_failure_is_not_retried_even_when_the_request_is_keyed(gateway, sleeps, make_error):
    gateway.fail(make_error(generate_readable_string(12)))

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        with pytest.raises(HttpClientError):
            await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_class", [httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError, httpx.ConnectError])
async def test_an_error_of_httpx_with_no_tls_error_behind_it_is_retried_by_its_kind(gateway, sleeps, error_class):
    # A stream that broke, the end of a stream (httpx reports it as a protocol error) or a connect that failed plainly.
    gateway.sequence(error_class(generate_readable_string(12)), make_success_step())

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_a_failure_to_set_up_the_client_outside_async_with_is_not_retried(monkeypatch, sleeps):
    # A malformed SSL_CERT_FILE: httpx reads the certificates when it builds the client.
    built = []
    error = tls_error("NO_CERTIFICATE_OR_CRL_FOUND", generate_readable_string(12))

    def broken(*args, **kwargs):
        built.append(1)
        raise error

    monkeypatch.setattr(httpx, "AsyncClient", broken)
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    with pytest.raises(HttpClientError) as exc:
        await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert exc.value.message.startswith("Client set-up failed: SSLError")
    assert exc.value.__cause__ is error
    assert len(built) == 1
    assert sleeps == []


class TrackingClient(httpx.AsyncClient):
    """An httpx client that records how often it is closed."""

    closed = 0
    built = 0
    close_error = None
    close_gate = None  # an Event that a close waits for, to cancel a call while it is closing
    completed = 0  # closes that ran to the end

    def __init__(self, *args, **kwargs):
        type(self).built += 1
        super().__init__(*args, **kwargs)

    async def aclose(self):
        type(self).closed += 1
        if type(self).close_gate is not None:
            await type(self).close_gate.wait()
        await super().aclose()
        type(self).completed += 1
        if type(self).close_error is not None:
            raise type(self).close_error


@pytest.fixture
def tracking(gateway, monkeypatch):
    """Every client the SDK builds is a TrackingClient that talks to the fake gateway."""
    TrackingClient.closed = 0
    TrackingClient.built = 0
    TrackingClient.close_error = None
    TrackingClient.close_gate = None
    TrackingClient.completed = 0

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(gateway)
        return TrackingClient(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return TrackingClient


@pytest.mark.asyncio
async def test_a_client_built_for_a_call_outside_async_with_is_closed_after_it(gateway, tracking):
    gateway.respond(body=make_order_status_response())

    await AsyncHttpClient(f"https://{generate_random_host()}").get(any_path())

    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_a_call_closes_its_client_also_when_it_fails(gateway, sleeps, tracking):
    gateway.fail(httpx.ReadTimeout(generate_readable_string(8)))

    with pytest.raises(HttpClientError):
        await AsyncHttpClient(f"https://{generate_random_host()}").post(any_path(), request_body=any_body(), headers=keyed())

    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_the_client_of_async_with_is_left_open_by_a_call_and_closed_on_exit(gateway, tracking):
    gateway.respond(body=make_order_status_response())

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.get(any_path())
        await http.get(any_path())
        assert tracking.closed == 0

    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_a_client_of_async_with_entered_after_a_call_outside_it_is_closed_once_on_exit(gateway, tracking):
    gateway.respond(body=make_order_status_response())
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    await http.get(any_path())  # outside `async with`: owns and closes its client
    assert tracking.closed == 1
    async with http:
        await http.get(any_path())
        assert tracking.closed == 1

    assert tracking.closed == 2


@pytest.mark.asyncio
async def test_the_last_exit_does_not_close_the_client_under_a_call_of_another_task(gateway, tracking, monkeypatch):
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()

    await http.__aenter__()  # one task holds the context
    monkeypatch.setattr(http, "_attempts", slow)
    call = asyncio.create_task(http.get(any_path()))  # another task calls outside it and borrows the client
    await started.wait()

    await http.__aexit__(None, None, None)  # the holder leaves while the call is in flight

    assert tracking.closed == 0
    release.set()
    await call
    assert tracking.closed == 1  # closed by the call that was the last user


@pytest.mark.asyncio
async def test_a_call_in_flight_does_not_close_a_client_that_was_opened_again(gateway, tracking, monkeypatch):
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()

    await http.__aenter__()
    monkeypatch.setattr(http, "_attempts", slow)
    call = asyncio.create_task(http.get(any_path()))
    await started.wait()
    await http.__aexit__(None, None, None)
    await http.__aenter__()  # entered again while the call is still using the first client

    release.set()
    await call

    assert tracking.closed == 0  # the context is open: nobody closes the client
    await http.__aexit__(None, None, None)
    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_tasks_entering_and_leaving_the_same_client_share_one_and_close_it_once(gateway, tracking):
    gateway.respond(body=make_order_status_response())
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    async def use():
        async with http:
            await asyncio.sleep(0)
            await http.get(any_path())
            await asyncio.sleep(0)

    await asyncio.gather(use(), use(), use())

    assert tracking.built == 1
    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_a_failing_close_does_not_replace_the_result_of_a_call_outside_async_with(client, gateway, tracking, platform):
    response = make_order_status_response()
    gateway.respond(body=response)
    tracking.close_error = RuntimeError(generate_readable_string(12))

    status = await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert status.status == response["status"]
    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_a_failing_close_does_not_replace_the_result_of_a_borrowed_call_that_is_the_last_user(
    client, gateway, tracking, platform
):
    response = make_order_status_response()
    gateway.respond(body=response)
    http = client._http_client
    original = http._attempts

    async def holder_leaves_first(*args, **kwargs):
        await client.__aexit__(None, None, None)  # the call becomes the last user
        return await original(*args, **kwargs)

    await client.__aenter__()
    http._attempts = holder_leaves_first
    tracking.close_error = RuntimeError(generate_readable_string(12))

    status = await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert status.status == response["status"]
    assert tracking.closed == 1
    assert http._in_flight == 0 and http._client is None


@pytest.mark.asyncio
async def test_the_count_of_calls_is_balanced_when_a_borrowed_call_fails(gateway, tracking):
    gateway.fail(httpx.ReadTimeout(generate_readable_string(8)))
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    async with http:
        with pytest.raises(HttpClientError):
            await http.get(any_path())
        assert http._in_flight == 0
        assert tracking.closed == 0

    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_the_count_of_calls_is_balanced_when_a_borrowed_call_is_cancelled_and_the_client_is_closed(
    gateway, tracking, monkeypatch
):
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    started = asyncio.Event()

    async def never_ends(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    await http.__aenter__()
    monkeypatch.setattr(http, "_attempts", never_ends)
    call = asyncio.create_task(http.get(any_path()))
    await started.wait()
    await http.__aexit__(None, None, None)  # the call is the last user
    assert tracking.closed == 0

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call

    assert http._in_flight == 0
    assert tracking.closed == 1  # the cancelled call still closed the client (the close is shielded)


@pytest.mark.asyncio
async def test_calls_outside_async_with_while_another_task_holds_it_share_the_client_and_it_is_closed_once(gateway, tracking):
    gateway.respond(body=make_order_status_response())
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    entered, release = asyncio.Event(), asyncio.Event()

    async def holder():
        async with http:
            entered.set()
            await release.wait()

    async def borrower():
        await entered.wait()
        await http.get(any_path())
        await asyncio.sleep(0)
        await http.get(any_path())

    holding = asyncio.create_task(holder())
    borrowers = [asyncio.create_task(borrower()) for _ in range(3)]
    await entered.wait()
    await asyncio.gather(*borrowers)
    assert tracking.closed == 0
    release.set()
    await holding

    assert tracking.built == 1
    assert tracking.closed == 1
    assert http._in_flight == 0


@pytest.mark.asyncio
async def test_leaving_more_often_than_entering_warns_and_changes_nothing(gateway, tracking):
    gateway.respond(body=make_order_status_response())
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    with pytest.warns(RuntimeWarning, match="0.3.0"):
        await http.__aexit__(None, None, None)

    async with http:
        await http.get(any_path())
    with pytest.warns(RuntimeWarning):
        await http.__aexit__(None, None, None)

    assert tracking.closed == 1
    assert http._entered == 0 and http._client is None


async def until(condition):
    """Let the event loop run until the condition holds; fail, not hang, if it does not."""

    async def spin():
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(spin(), WAIT_LIMIT_SECONDS)


def last_user_closes(http, monkeypatch):
    """Make the next call the last user of the client: the holder leaves while the call is running."""

    async def holder_leaves_first(*args, **kwargs):
        await http.__aexit__(None, None, None)

    monkeypatch.setattr(http, "_attempts", holder_leaves_first)


@pytest.mark.asyncio
@pytest.mark.parametrize("hook_passes_the_error", [True, False], ids=["exc_info-given", "hand-written-None"])
async def test_an_exit_without_an_entry_does_not_replace_an_error_that_is_propagating(caplog, hook_passes_the_error):
    # A merchant's filters can turn a warning into an error; while an error propagates, the warning goes to the log,
    # also when a shutdown hook written by hand passes None instead of the error.
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    marker = generate_readable_string(8)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
            with pytest.raises(KeyError, match=marker):
                try:
                    raise KeyError(marker)
                finally:
                    await http.__aexit__(*(sys.exc_info() if hook_passes_the_error else (None, None, None)))

    assert "exited more often than it was entered" in caplog.text


@pytest.mark.asyncio
async def test_the_warning_of_an_unbalanced_exit_points_at_the_code_of_the_merchant(client):
    with pytest.warns(RuntimeWarning) as caught:
        await client.__aexit__(None, None, None)  # through the public client, two frames of the SDK deep

    assert caught[0].filename == __file__


@pytest.mark.asyncio
async def test_a_call_cancelled_while_it_closes_leaves_at_once_and_the_close_goes_on(gateway, tracking, monkeypatch):
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    gate = tracking.close_gate = asyncio.Event()
    await http.__aenter__()
    last_user_closes(http, monkeypatch)
    call = asyncio.create_task(http.get(any_path()))
    await until(lambda: tracking.closed == 1)  # the close has started and waits at the gate

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call  # the caller is not kept waiting for the close
    assert tracking.completed == 0 and len(http._closing) == 1

    gate.set()
    await until(lambda: not http._closing)  # the close task ends by itself and is dropped

    assert tracking.completed == 1  # the connections were closed in the background


@pytest.mark.asyncio
@pytest.mark.parametrize("steps", range(7))
async def test_a_caller_cancelled_around_the_moment_the_close_task_is_cancelled_gets_its_cancellation(
    gateway, tracking, monkeypatch, steps
):
    # The caller is cancelled `steps` turns of the event loop after the close task: the windows differ between Python
    # versions (how many tasks `wait_for` and the like put between), so every one of them is tried.
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    tracking.close_gate = asyncio.Event()  # never set
    await http.__aenter__()
    last_user_closes(http, monkeypatch)
    call = asyncio.create_task(http.get(any_path()))
    await until(lambda: tracking.closed == 1)

    for task in list(http._closing):
        task.cancel()
    for _ in range(steps):
        await asyncio.sleep(0)
    finished_before = call.done()  # a call that has already returned is not cancelled by a later cancel(): that is fine
    call.cancel()

    if finished_before:
        await call
    else:
        with pytest.raises(asyncio.CancelledError):
            await call
        assert call.cancelled()


@pytest.mark.asyncio
async def test_a_close_cancelled_before_it_ended_is_logged(gateway, tracking, caplog):
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    tracking.close_gate = asyncio.Event()  # never set
    await http.__aenter__()

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        closing = asyncio.create_task(http.__aexit__(None, None, None))
        await until(lambda: tracking.closed == 1)
        for task in list(http._closing):
            task.cancel()
        await closing  # the exit goes on: only the close task was cancelled
        await until(lambda: not http._closing)

    assert "was cancelled before it ended" in caplog.text


@pytest.mark.asyncio
async def test_a_timeout_error_of_the_close_itself_is_not_taken_for_the_deadline(client, gateway, tracking, platform, caplog):
    gateway.respond(body=make_order_status_response())
    text = generate_readable_string(12)
    tracking.close_error = TimeoutError(text)  # raised by aclose at once, long before CLOSE_TIMEOUT

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert "timed out" not in caplog.text
    assert f"Closing the HTTP client failed: TimeoutError: {text}" in caplog.text
    assert caplog.records[-1].exc_info is not None


@pytest.mark.asyncio
async def test_a_timeout_of_the_transports_own_deadline_inside_the_close_is_not_taken_for_the_sdks(
    client, gateway, tracking, platform, caplog
):
    gateway.respond(body=make_order_status_response())
    error = TimeoutError(generate_readable_string(12))
    error.__cause__ = asyncio.CancelledError()  # what a `wait_for` or `timeout` of the transport itself leaves behind
    tracking.close_error = error

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert "timed out" not in caplog.text
    assert "Closing the HTTP client failed: TimeoutError" in caplog.text


@pytest.mark.asyncio
async def test_the_warning_of_an_unbalanced_exit_is_emitted_when_an_error_was_handled_by_the_caller_of_the_loop(client):
    # The usual shutdown: `except KeyboardInterrupt: asyncio.run(cleanup())`. Nothing is propagating inside the cleanup.
    try:
        raise KeyboardInterrupt
    except KeyboardInterrupt:
        with pytest.warns(RuntimeWarning, match="exited more often"):
            await client.__aexit__(None, None, None)


@pytest.mark.parametrize(
    "name, is_sdk",
    [
        (sdk.__name__, True),
        (f"{sdk.__name__}.{generate_readable_string(6)}", True),
        (f"{sdk.__name__}.{generate_readable_string(6)}.{generate_readable_string(6)}", True),
        (f"{sdk.__name__}{generate_readable_string(6)}", False),
        (f"{sdk.__name__}_{generate_readable_string(6)}.{generate_readable_string(6)}", False),
        (sdk.__name__.split(".")[0], False),
        (generate_readable_string(8), False),
    ],
)
def test_only_the_modules_of_the_sdk_package_are_skipped_when_the_warning_looks_for_the_merchant(name, is_sdk):
    assert _is_sdk_module(name) is is_sdk


@pytest.mark.asyncio
async def test_a_cancellation_of_the_close_task_itself_does_not_reach_a_caller_that_was_not_cancelled(
    client, gateway, tracking, platform, monkeypatch
):
    response = make_order_status_response()
    gateway.respond(body=response)
    tracking.close_gate = asyncio.Event()  # the close waits, so the task can be cancelled from outside
    http = client._http_client

    async def cancel_the_close_task():
        await until(lambda: http._closing)
        for task in list(http._closing):
            task.cancel()

    canceller = asyncio.create_task(cancel_the_close_task())
    status = await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)
    await canceller

    assert status.status == response["status"]


@pytest.mark.asyncio
async def test_a_close_that_hangs_is_bounded_and_logged_and_the_call_returns_its_result(
    client, gateway, tracking, platform, monkeypatch, caplog
):
    response = make_order_status_response()
    gateway.respond(body=response)
    tracking.close_gate = asyncio.Event()  # never set
    monkeypatch.setattr("polako.sdk._async_client.CLOSE_TIMEOUT", generate_short_timeout())

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        status = await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert status.status == response["status"]
    assert "timed out" in caplog.text and "may stay open" in caplog.text


@pytest.mark.asyncio
async def test_a_failed_close_is_logged_with_its_traceback_not_lost(client, gateway, tracking, platform, caplog):
    gateway.respond(body=make_order_status_response())
    text = generate_readable_string(12)
    tracking.close_error = RuntimeError(text)

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert f"Closing the HTTP client failed: RuntimeError: {text}" in caplog.text
    assert caplog.records[-1].exc_info is not None


@pytest.mark.asyncio
async def test_a_failing_close_at_the_exit_of_async_with_does_not_replace_the_error_that_is_propagating(
    gateway, tracking, caplog
):
    tracking.close_error = RuntimeError(generate_readable_string(12))
    http = AsyncHttpClient(f"https://{generate_random_host()}")
    marker = generate_readable_string(8)

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        with pytest.raises(KeyError, match=marker):
            async with http:
                raise KeyError(marker)

    assert tracking.closed == 1 and "Closing the HTTP client failed" in caplog.text


@pytest.mark.asyncio
async def test_a_close_that_hangs_at_the_exit_of_async_with_is_bounded(gateway, tracking, monkeypatch, caplog):
    tracking.close_gate = asyncio.Event()  # never set
    monkeypatch.setattr("polako.sdk._async_client.CLOSE_TIMEOUT", generate_short_timeout())

    with caplog.at_level(logging.WARNING, logger="polako.sdk._async_client"):
        async with AsyncHttpClient(f"https://{generate_random_host()}"):
            pass

    assert "timed out" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [REFUND_REASON_MIN_LENGTH, REFUND_REASON_MAX_LENGTH])
async def test_a_refund_reason_of_exactly_the_limit_is_accepted(client, gateway, platform, length):
    session_id = uuid4()
    gateway.respond(body=make_refund_response(session_id=str(session_id), session_status="REFUNDED"))
    reason = generate_readable_string(length)

    async with client:
        await client.refund_session(session_id, platform.platform_id, platform.secret_key, reason)

    assert gateway.last_json()["reason"] == reason


def test_the_limits_of_the_refund_reason_are_exported():
    assert sdk.REFUND_REASON_MIN_LENGTH == REFUND_REASON_MIN_LENGTH < REFUND_REASON_MAX_LENGTH == sdk.REFUND_REASON_MAX_LENGTH


@pytest.mark.asyncio
async def test_async_with_entered_twice_shares_one_client_and_closes_it_with_the_last_exit(gateway, tracking):
    gateway.respond(body=make_order_status_response())
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    async with http:
        first = http._client
        async with http:
            assert http._client is first
            await http.get(any_path())
        assert tracking.closed == 0
        await http.get(any_path())

    assert tracking.closed == 1


@pytest.mark.asyncio
async def test_a_malformed_certificate_file_fails_at_set_up(monkeypatch, tmp_path):
    # The real httpx reads SSL_CERT_FILE when it builds the client (no stand-in for the client here).
    bad = tmp_path / generate_readable_string(8)
    bad.write_text(generate_readable_string(40))
    monkeypatch.setenv("SSL_CERT_FILE", str(bad))

    with pytest.raises(HttpClientError) as exc:
        async with AsyncHttpClient(f"https://{generate_random_host()}"):
            pass

    assert exc.value.message.startswith("Client set-up failed: ")
    assert exc.value.__cause__ is not None


@pytest.mark.asyncio
async def test_a_proxy_setting_that_cannot_be_used_is_a_client_error_not_a_raw_value_error(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALL_PROXY", f"{generate_readable_string(6).lower()}://{generate_random_host()}")

    with pytest.raises(HttpClientError) as exc:
        async with AsyncHttpClient(f"https://{generate_random_host()}"):  # the set-up only: nothing is sent
            pass

    assert exc.value.message.startswith("Client set-up failed: ")
    assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_a_malformed_proxy_url_is_a_client_error_not_a_raw_httpx_error(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "HTTPS_PROXY", f"http://{generate_random_host()}:{generate_readable_string(3)}"
    )  # a port that is not a number

    with pytest.raises(HttpClientError) as exc:
        async with AsyncHttpClient(f"https://{generate_random_host()}"):  # the set-up only: nothing is sent
            pass

    assert exc.value.message.startswith("Client set-up failed: ")
    assert isinstance(exc.value.__cause__, httpx.InvalidURL)


@pytest.mark.asyncio
async def test_a_mistake_in_the_code_at_set_up_is_not_turned_into_a_client_error(monkeypatch):
    def broken(*args, **kwargs):
        raise TypeError(generate_readable_string(12))

    monkeypatch.setattr(httpx, "AsyncClient", broken)

    with pytest.raises(TypeError):
        async with AsyncHttpClient(f"https://{generate_random_host()}"):
            pass


@pytest.mark.asyncio
async def test_one_client_serves_all_attempts_outside_async_with(gateway, sleeps, monkeypatch):
    built = []
    real = httpx.AsyncClient

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", counting)
    gateway.sequence(
        httpx.ReadTimeout(generate_readable_string(8)), httpx.ReadTimeout(generate_readable_string(8)), make_success_step()
    )
    http = AsyncHttpClient(f"https://{generate_random_host()}")

    await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 3
    assert len(built) == 1


@pytest.mark.asyncio
async def test_the_message_of_a_retried_request_says_how_many_attempts_were_made(gateway, sleeps):
    gateway.fail(httpx.ReadTimeout(""))

    async with AsyncHttpClient(f"https://{generate_random_host()}", max_attempts=3) as http:
        with pytest.raises(HttpClientError) as exc:
            await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert exc.value.message == "Request failed: ReadTimeout (after 3 attempts; the message is about the last one)"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_the_message_of_an_answer_after_retries_says_how_many_attempts_were_made(gateway, sleeps, status):
    detail = generate_readable_string(12)
    gateway.respond(status=status, text=detail)

    async with AsyncHttpClient(f"https://{generate_random_host()}", max_attempts=3) as http:
        with pytest.raises(HttpRequestError) as exc:
            await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert exc.value.message == (
        f"HTTP request failed with status {status}: {detail} (after 3 attempts; the message is about the last one)"
    )


@pytest.mark.asyncio
async def test_the_message_of_an_answer_to_a_single_attempt_has_no_attempt_count(client, gateway):
    detail = generate_readable_string(12)
    gateway.respond(status=404, text=detail)

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == f"HTTP request failed with status 404: {detail}"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 502])
async def test_an_error_answer_with_an_empty_body_does_not_end_after_the_colon(client, gateway, status):
    gateway.respond(status=status, text="")

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == f"HTTP request failed with status {status}"


@pytest.mark.asyncio
async def test_an_error_the_caller_is_handling_is_not_taken_for_the_reason_of_a_new_failure(gateway, sleeps):
    # A merchant retries inside `except`: the old error is the __context__ of whatever the new call raises.
    gateway.sequence(httpx.ReadTimeout(generate_readable_string(8)), make_success_step())

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        try:
            raise ssl.SSLCertVerificationError(generate_readable_string(12))
        except ssl.SSLCertVerificationError:
            await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_the_message_does_not_show_the_text_of_an_error_the_caller_is_handling(gateway, sleeps):
    old_text = generate_readable_string(12)
    gateway.fail(httpx.ReadTimeout(""))

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        try:
            raise ConnectionResetError(old_text)
        except ConnectionResetError:
            with pytest.raises(HttpClientError) as exc:
                await http.get(any_path())

    assert exc.value.message == "Request failed: ReadTimeout"


@pytest.mark.asyncio
async def test_the_walk_over_the_chain_stops_at_an_error_of_the_sdk(gateway, sleeps):
    error = httpx.ReadTimeout(generate_readable_string(8))
    error.__cause__ = HttpClientError(generate_readable_string(8))
    error.__cause__.__cause__ = ssl.SSLCertVerificationError(generate_readable_string(12))
    gateway.sequence(error, make_success_step())

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_a_failure_to_set_up_the_client_in_async_with_is_a_client_error(monkeypatch):
    # e.g. SSL_CERT_FILE points to a file that is missing
    error = FileNotFoundError(generate_readable_string(12))

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(httpx, "AsyncClient", broken)

    with pytest.raises(HttpClientError) as exc:
        async with PolakoClient():
            pass

    assert not isinstance(exc.value, HttpRequestError)
    assert exc.value.message == f"Client set-up failed: FileNotFoundError: {error}"
    assert exc.value.__cause__ is error


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["\n", " ", "\t", "\r\n"])
async def test_an_api_key_with_whitespace_at_the_end_is_refused_without_the_key_in_the_error(gateway, credentials, suffix):
    key = credentials.api_key + suffix
    client = PolakoClient(test_env=True, company_id=credentials.company_id, api_key=key)

    with pytest.raises(ConfigurationError) as exc:
        async with client:
            await client.get_subscription(uuid4())

    assert credentials.api_key not in str(exc.value) and credentials.api_key not in repr(exc.value)
    assert "newline" in exc.value.args[0]
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_key",
    [
        lambda: uuid4(),
        lambda: random.randint(10**8, 10**9),
        lambda: generate_readable_string(8).encode("ascii"),
        lambda: b"",
        lambda: 0,
    ],
    ids=["uuid", "int", "bytes", "empty-bytes", "zero"],
)
async def test_an_api_key_of_another_type_is_refused_with_a_message_about_the_type(gateway, credentials, make_key):
    key = make_key()
    client = PolakoClient(test_env=True, company_id=credentials.company_id, api_key=key)

    with pytest.raises(ConfigurationError) as exc:
        async with client:
            await client.get_subscription(uuid4())

    assert "must be a string" in exc.value.args[0] and type(key).__name__ in exc.value.args[0]
    assert "newline" not in exc.value.args[0]
    assert str(key) not in str(exc.value) and repr(key) not in repr(exc.value)
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_a_non_ascii_idempotency_key_is_refused_before_any_request(gateway, subscription_client):
    key = generate_readable_string(6) + "\u017e"

    with pytest.raises(InvalidHeaderValueError, match="idempotency_key") as exc:
        async with subscription_client:
            await subscription_client.create_subscription(**make_subscribe_args(), idempotency_key=key)

    assert key not in str(exc.value)
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_a_uuid_is_accepted_as_the_idempotency_key_and_sent_as_text(gateway, subscription_client):
    key = uuid4()
    gateway.respond(status=201, body=make_subscribe_response())

    async with subscription_client:
        created = await subscription_client.create_subscription(**make_subscribe_args(), idempotency_key=key)

    assert created.idempotency_key == str(key)
    assert gateway.last.headers["Idempotency-Key"] == str(key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key", [random.randint(10**8, 10**9), generate_readable_string(8).encode("ascii"), [generate_readable_string(4)], "", "  "]
)
async def test_an_idempotency_key_that_is_blank_or_not_text_is_an_invalid_header_value(gateway, subscription_client, key):
    with pytest.raises(InvalidHeaderValueError, match="idempotency_key"):
        async with subscription_client:
            await subscription_client.create_subscription(**make_subscribe_args(), idempotency_key=key)

    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_value",
    [
        lambda secret: secret + "\n",
        lambda secret: " " + secret,
        lambda secret: secret + "\u017e",
        lambda secret: secret + "\x00",
        lambda secret: random.randint(10**8, 10**9),
        lambda secret: secret.encode("ascii") + b"\n",
    ],
    ids=["newline", "leading-space", "non-ascii", "control", "int", "bytes"],
)
async def test_a_header_value_that_cannot_be_sent_is_refused_naming_only_the_header(gateway, make_value):
    name = generate_readable_string(8)
    secret = generate_readable_string(16)
    value = make_value(secret)

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        with pytest.raises(InvalidHeaderValueError) as exc:
            await http.get(any_path(), headers={name: value})

    assert name in str(exc.value)
    for leaked in (secret, str(value), repr(value)):
        assert leaked not in str(exc.value) and leaked not in repr(exc.value)
    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_name",
    [
        lambda: "",
        lambda: generate_readable_string(4) + " " + generate_readable_string(4),
        lambda: generate_readable_string(4) + "\u017e",
        lambda: generate_readable_string(4) + " ",
        lambda: generate_readable_string(4) + ":",
    ],
)
async def test_a_header_name_that_cannot_be_sent_is_refused_before_the_request(gateway, make_name):
    name = make_name()

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        with pytest.raises(InvalidArgumentError) as exc:
            await http.get(any_path(), headers={name: generate_readable_string(8)})

    assert repr(name) in str(exc.value)
    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_value",
    [
        lambda: generate_readable_string(6).encode("ascii"),
        lambda: generate_readable_string(3) + "\t" + generate_readable_string(3),
    ],
    ids=["bytes", "inner-tab"],
)
async def test_a_header_value_httpx_can_send_is_sent(gateway, make_value):
    name = generate_readable_string(8)
    value = make_value()
    gateway.respond(body=any_body())

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.get(any_path(), headers={name: value})

    assert len(gateway.requests) == 1
    assert gateway.last.headers[name].encode("ascii") == (value if isinstance(value, bytes) else value.encode("ascii"))


@pytest.mark.asyncio
async def test_invalid_arguments_are_typed_and_still_value_errors(client, gateway, platform):
    async with client:
        with pytest.raises(InvalidArgumentError) as exc:
            await client.refund_session(
                uuid4(), platform.platform_id, platform.secret_key, generate_readable_string(REFUND_REASON_MIN_LENGTH - 1)
            )

    assert isinstance(exc.value, ValueError)
    assert not isinstance(exc.value, ConfigurationError)
    assert gateway.requests == []
    assert issubclass(InvalidHeaderValueError, InvalidArgumentError)
