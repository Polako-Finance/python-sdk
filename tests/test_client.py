"""Every public payment method of the client against a fake gateway."""

from uuid import uuid4

import httpx
import pytest

from polako.sdk import HttpClientError, HttpRequestError, PolakoClient
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
    gateway.fail(httpx.ConnectError(generate_readable_string(12)))

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(uuid4())

    assert not isinstance(exc.value, HttpRequestError)


@pytest.mark.asyncio
async def test_works_without_context_manager(client, gateway, platform):
    response = make_order_status_response()
    gateway.respond(body=response)

    status = await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert status.status == response["status"]
