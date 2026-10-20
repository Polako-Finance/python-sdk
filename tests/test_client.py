"""Every public payment method of the client against a fake gateway."""

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
    make_init_customer_info,
    make_order_details,
    make_order_status_response,
    make_payment_url_response,
    make_refund_item,
    make_refund_response,
    make_session_details_response,
    make_session_info_response,
    sign,
)
from tests.generators import generate_readable_string


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
    assert gateway.last.url.host == "stg-api.infra.polako-finance.com"
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

    assert gateway.last.url.host == "api.infra.polako-finance.com"


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
    error = httpx.ConnectError("")
    error.__context__ = ConnectionResetError("Connection reset by peer")
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == "Request failed: ConnectError: ConnectionResetError: Connection reset by peer"


@pytest.mark.asyncio
async def test_a_failure_that_httpx_does_not_wrap_is_still_a_client_error_not_a_gateway_answer(client, gateway):
    error = ssl.SSLError("[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] decryption failed")
    gateway.fail(error)

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert not isinstance(exc.value, HttpRequestError)
    assert exc.value.__cause__ is error


@pytest.mark.asyncio
async def test_a_tls_failure_after_the_handshake_is_retried_when_the_request_is_keyed(gateway, sleeps):
    gateway.sequence(ssl.SSLError("[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC]"), {"status": 200, "body": {}})

    async with AsyncHttpClient("https://example.test") as http:
        await http.post("/v1/anything", request_body={"a": 1}, headers={"Idempotency-Key": "k-1"})

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_the_message_of_a_retried_request_says_how_many_attempts_were_made(gateway, sleeps):
    gateway.fail(httpx.ReadTimeout(""))

    async with AsyncHttpClient("https://example.test", max_attempts=3) as http:
        with pytest.raises(HttpClientError) as exc:
            await http.post("/v1/anything", request_body={"a": 1}, headers={"Idempotency-Key": "k-1"})

    assert exc.value.message == "Request failed: ReadTimeout (after 3 attempts; this is the error of the last one)"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 502])
async def test_an_error_answer_with_an_empty_body_does_not_end_after_the_colon(client, gateway, status):
    gateway.respond(status=status, text="")

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(uuid4())

    assert exc.value.message == f"HTTP request failed with status {status}"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["\n", " ", "\t", "\r\n"])
async def test_an_api_key_with_whitespace_at_the_end_is_refused_without_the_key_in_the_error(gateway, credentials, suffix):
    key = credentials.api_key + suffix
    client = PolakoClient(test_env=True, company_id=credentials.company_id, api_key=key)

    with pytest.raises(ConfigurationError) as exc:
        async with client:
            await client.get_subscription(uuid4())

    assert credentials.api_key not in str(exc.value) and credentials.api_key not in repr(exc.value)
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_a_non_ascii_idempotency_key_is_refused_before_any_request(gateway, subscription_client):
    with pytest.raises(InvalidHeaderValueError, match="idempotency_key"):
        async with subscription_client:
            await subscription_client.create_subscription(
                customer_email="a@example.com",
                amount=10,
                currency="RSD",
                billing_interval="monthly",
                merchant_subscription_ref="ref-1",
                success_url="https://example.com/ok",
                cancel_url="https://example.com/cancel",
                error_url="https://example.com/error",
                idempotency_key="porud\u017ebina-17",
            )

    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["secret\n", " secret", "se\u017eret", "se\x00cret"])
async def test_a_header_value_that_cannot_be_sent_is_refused_naming_only_the_header(gateway, value):
    async with AsyncHttpClient("https://example.test") as http:
        with pytest.raises(InvalidHeaderValueError) as exc:
            await http.get("/v1/anything", headers={"x-token": value})

    assert "x-token" in str(exc.value)
    assert value.strip() not in str(exc.value)
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_invalid_arguments_are_typed_and_still_value_errors(client, gateway, platform):
    async with client:
        with pytest.raises(InvalidArgumentError) as exc:
            await client.refund_session(uuid4(), platform.platform_id, platform.secret_key, "no")

    assert isinstance(exc.value, ValueError)
    assert not isinstance(exc.value, ConfigurationError)
    assert gateway.requests == []
    assert issubclass(InvalidHeaderValueError, InvalidArgumentError)
