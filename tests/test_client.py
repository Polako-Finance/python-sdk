"""Every public payment method of the client against a fake gateway."""

import random
import ssl
from uuid import uuid4

import httpx
import pytest

from polako.sdk import (
    ConfigurationError,
    HttpClientError,
    HttpRequestError,
    InvalidArgumentError,
    InvalidHeaderValueError,
    PolakoClient,
)
from polako.sdk._async_client import AsyncHttpClient
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
    sign,
)
from tests.generators import generate_random_host, generate_readable_string


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
@pytest.mark.parametrize("reason, items", [("no", None), ("x" * 256, None), (generate_readable_string(20), [])])
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


def tls_error(reason: str, text: str) -> ssl.SSLError:
    """An ssl.SSLError the way OpenSSL raises it: the code is in `reason` and in the text."""
    error = ssl.SSLError(f"[SSL: {reason}] {text}")
    error.reason = reason  # type: ignore[attr-defined]
    return error


TRANSIENT_FAILURES = [
    pytest.param(lambda text: ssl.SSLEOFError(text), id="SSLEOFError"),
    pytest.param(lambda text: ssl.SSLZeroReturnError(text), id="SSLZeroReturnError"),
    pytest.param(lambda text: ssl.SSLSyscallError(text), id="SSLSyscallError"),
    pytest.param(lambda text: tls_error("BAD_RECORD_MAC", text), id="BAD_RECORD_MAC"),
    pytest.param(lambda text: tls_error("DECRYPTION_FAILED", text), id="DECRYPTION_FAILED"),
    pytest.param(lambda text: tls_error("RECORD_LAYER_FAILURE", text), id="RECORD_LAYER_FAILURE"),
    pytest.param(lambda text: tls_error("UNEXPECTED_RECORD", text), id="UNEXPECTED_RECORD"),
    pytest.param(lambda text: ConnectionResetError(text), id="ConnectionResetError"),
    pytest.param(lambda text: ConnectionAbortedError(text), id="ConnectionAbortedError"),
    pytest.param(lambda text: ConnectionRefusedError(text), id="ConnectionRefusedError"),
    pytest.param(lambda text: BrokenPipeError(text), id="BrokenPipeError"),
    pytest.param(lambda text: TimeoutError(text), id="TimeoutError"),
]

PERMANENT_FAILURES = [
    pytest.param(lambda text: ssl.SSLCertVerificationError(text), id="SSLCertVerificationError"),
    pytest.param(lambda text: tls_error("CERTIFICATE_VERIFY_FAILED", text), id="CERTIFICATE_VERIFY_FAILED"),
    pytest.param(lambda text: tls_error("WRONG_VERSION_NUMBER", text), id="WRONG_VERSION_NUMBER"),
    pytest.param(lambda text: tls_error("TLSV1_ALERT_PROTOCOL_VERSION", text), id="TLSV1_ALERT_PROTOCOL_VERSION"),
    pytest.param(lambda text: tls_error("UNSUPPORTED_PROTOCOL", text), id="UNSUPPORTED_PROTOCOL"),
    pytest.param(lambda text: FileNotFoundError(text), id="FileNotFoundError"),
    pytest.param(lambda text: PermissionError(text), id="PermissionError"),
]


def wrapped_by_httpx(make_cause):
    def make(text):
        error = httpx.ConnectError("")
        error.__cause__ = make_cause(text)
        return error

    return make


@pytest.mark.asyncio
@pytest.mark.parametrize("make_error", TRANSIENT_FAILURES + PERMANENT_FAILURES)
async def test_a_failure_that_httpx_does_not_wrap_is_a_client_error_not_a_gateway_answer(client, gateway, make_error):
    error = make_error(generate_readable_string(12))
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert not isinstance(exc.value, HttpRequestError)
    assert exc.value.__cause__ is error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_error",
    TRANSIENT_FAILURES
    + [
        pytest.param(wrapped_by_httpx(lambda text: tls_error("RECORD_LAYER_FAILURE", text)), id="wrapped-RECORD_LAYER_FAILURE"),
        pytest.param(wrapped_by_httpx(lambda text: ssl.SSLSyscallError(text)), id="wrapped-SSLSyscallError"),
    ],
)
async def test_a_transient_failure_is_retried_when_the_request_is_keyed(gateway, sleeps, make_error):
    gateway.sequence(make_error(generate_readable_string(12)), {"status": 200, "body": {}})

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_error",
    PERMANENT_FAILURES
    + [
        pytest.param(wrapped_by_httpx(lambda text: ssl.SSLCertVerificationError(text)), id="wrapped-certificate"),
        pytest.param(wrapped_by_httpx(lambda text: tls_error("WRONG_VERSION_NUMBER", text)), id="wrapped-WRONG_VERSION_NUMBER"),
    ],
)
async def test_a_permanent_failure_is_not_retried_even_when_the_request_is_keyed(gateway, sleeps, make_error):
    gateway.fail(make_error(generate_readable_string(12)))

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        with pytest.raises(HttpClientError):
            await http.post(any_path(), request_body=any_body(), headers=keyed())

    assert len(gateway.requests) == 1


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
    gateway.sequence(httpx.ReadTimeout(""), {"status": 200, "body": {}})

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
    error = httpx.ReadTimeout("")
    error.__cause__ = HttpClientError(generate_readable_string(8))
    error.__cause__.__cause__ = ssl.SSLCertVerificationError(generate_readable_string(12))
    gateway.sequence(error, {"status": 200, "body": {}})

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
    gateway.respond(body={})

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.get(any_path(), headers={name: value})

    assert len(gateway.requests) == 1
    assert gateway.last.headers[name].encode("ascii") == (value if isinstance(value, bytes) else value.encode("ascii"))


@pytest.mark.asyncio
async def test_invalid_arguments_are_typed_and_still_value_errors(client, gateway, platform):
    async with client:
        with pytest.raises(InvalidArgumentError) as exc:
            await client.refund_session(uuid4(), platform.platform_id, platform.secret_key, generate_readable_string(2))

    assert isinstance(exc.value, ValueError)
    assert not isinstance(exc.value, ConfigurationError)
    assert gateway.requests == []
    assert issubclass(InvalidHeaderValueError, InvalidArgumentError)
