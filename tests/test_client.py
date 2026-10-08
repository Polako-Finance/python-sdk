"""Smoke: every public client method against a fake gateway."""

from decimal import Decimal
from uuid import uuid4

import pytest

from polako.sdk import (
    CustomerInfo,
    HttpClientError,
    HttpRequestError,
    InitCustomerInfo,
    OrderDetails,
    OrderItem,
    PolakoClient,
    RefundItem,
)

PLATFORM_ID = uuid4()
SECRET = "test-secret"
SESSION_ID = uuid4()


def make_order() -> OrderDetails:
    item = OrderItem(code="SKU-1", name="Ticket", description=None, price=Decimal("100.00"), quantity=2, tax="VAT")
    return OrderDetails(currency=None, language=None, order_id="ORDER-1", items=[item], total=Decimal("200"))


def make_customer() -> CustomerInfo:
    return CustomerInfo(first_name="A", last_name="B", email="a@b.c", phone=None, address=None)


@pytest.mark.asyncio
async def test_create_order(client, gateway):
    gateway.respond(body={"paymentSessionId": "s1", "paymentPageUrl": "https://pay", "expiresAt": "2026-01-01T00:00:00"})

    async with client:
        session = await client.create_order(make_order(), make_customer(), PLATFORM_ID, SECRET)

    assert session.paymentSessionId == "s1"
    assert gateway.last.method == "POST"
    assert gateway.last.url.host == "stg-api.infra.polako-finance.com"
    assert gateway.last.url.path == "/v1/session/signed"
    body = gateway.last_json()
    assert body["currency"] == "RSD"
    assert body["language"] == "sr"
    assert body["total"] == "200.00"
    assert body["signature"] == PolakoClient._create_signature("ORDER-1|200.00|RSD", SECRET)


@pytest.mark.asyncio
async def test_create_order_validates_before_sending(client, gateway):
    order = make_order()
    order.items = []

    async with client:
        with pytest.raises(ValueError):
            await client.create_order(order, make_customer(), PLATFORM_ID, SECRET)

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_production_base_url_by_default(gateway):
    gateway.respond(body={"paymentSessionId": "s1", "paymentPageUrl": "u", "expiresAt": "e"})

    async with PolakoClient() as prod:
        await prod.create_order(make_order(), make_customer(), PLATFORM_ID, SECRET)

    assert gateway.last.url.host == "api.infra.polako-finance.com"


@pytest.mark.asyncio
async def test_get_session_details(client, gateway):
    gateway.respond(
        body={
            "session_id": str(SESSION_ID),
            "language_code": "en",
            "supported_languages": ["en"],
            "payment_config": None,
            "customer": {
                "first_name": "A",
                "last_name": "B",
                "email": None,
                "phone": None,
                "address": None,
                "type": None,
                "cgid": None,
            },
            "shopping_cart": {"items": [], "currency": "RSD", "total_price": 0},
            "payment_options": [],
            "terms_url": "https://terms",
        }
    )

    async with client:
        details = await client.get_session_details(SESSION_ID)

    assert details.session_id == str(SESSION_ID)
    assert gateway.last.method == "GET"
    assert gateway.last.url.path == f"/v1/session/{SESSION_ID}"


@pytest.mark.asyncio
async def test_get_payment_url(client, gateway):
    gateway.respond(body={"sessionId": str(SESSION_ID), "type": "redirect", "paymentUrl": "https://psp", "metadata": None})
    customer = InitCustomerInfo(
        first_name="A", last_name="B", email="a@b.c", phone=None, address=None, type="person", cgid=None
    )
    option_id = uuid4()

    async with client:
        result = await client.get_payment_url(SESSION_ID, option_id, customer, "en", True)

    assert result.paymentUrl == "https://psp"
    assert gateway.last.url.path == f"/v1/session/{SESSION_ID}/payment_url"
    body = gateway.last_json()
    assert body["payment_option_id"] == str(option_id)
    assert body["terms_accepted"] is True


@pytest.mark.asyncio
async def test_check_order_status(client, gateway):
    gateway.respond(
        body={
            "session_id": str(SESSION_ID),
            "status": "completed",
            "created_at": "2026-01-01",
            "total": 200.0,
            "currency": "RSD",
            "items": [],
        }
    )

    async with client:
        status = await client.check_order_status(SESSION_ID, PLATFORM_ID, SECRET)

    assert status.status == "completed"
    assert gateway.last.url.path == f"/v1/session/{SESSION_ID}/status/signed"
    assert gateway.last_json()["signature"] == PolakoClient._create_signature(f"status|{SESSION_ID}|{PLATFORM_ID}", SECRET)


@pytest.mark.asyncio
async def test_refund_full_and_partial(client, gateway):
    gateway.respond(
        body={
            "session_id": str(SESSION_ID),
            "session_status": "REFUNDED",
            "original_transaction_id": "t1",
            "refund_transaction_id": "t2",
            "refund_amount": 200.0,
            "original_amount": 200.0,
            "currency": "RSD",
            "refund_time": "2026-01-01",
        }
    )

    async with client:
        refund = await client.refund_session(SESSION_ID, PLATFORM_ID, SECRET, "customer request")
        assert refund.session_status == "REFUNDED"
        assert gateway.last.url.path == f"/v1/session/{SESSION_ID}/refund/signed"
        assert gateway.last_json()["is_full_refund"] is True

        await client.refund_session(SESSION_ID, PLATFORM_ID, SECRET, "customer request", [RefundItem("i1", 1)])
        body = gateway.last_json()
        assert body["is_full_refund"] is False
        assert body["refund_items"] == [{"item_id": "i1", "refund_quantity": 1, "item_code": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason, items", [("no", None), ("x" * 256, None), ("customer request", [])])
async def test_refund_argument_validation(client, gateway, reason, items):
    async with client:
        with pytest.raises(ValueError):
            await client.refund_session(SESSION_ID, PLATFORM_ID, SECRET, reason, items)

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_http_error_carries_status_and_body(client, gateway):
    gateway.respond(status=410, text='{"detail": "expired"}')

    async with client:
        with pytest.raises(HttpRequestError) as exc:
            await client.get_session_details(SESSION_ID)

    assert exc.value.status_code == 410
    assert "expired" in exc.value.response_body


@pytest.mark.asyncio
async def test_malformed_success_body_is_request_error(client, gateway):
    gateway.respond(text="not json")

    async with client:
        with pytest.raises(HttpRequestError):
            await client.get_session_details(SESSION_ID)


@pytest.mark.asyncio
async def test_network_error_is_client_error_not_request_error(client, gateway):
    import httpx

    gateway.fail(httpx.ConnectError("boom"))

    async with client:
        with pytest.raises(HttpClientError) as exc:
            await client.get_session_details(SESSION_ID)

    assert not isinstance(exc.value, HttpRequestError)


@pytest.mark.asyncio
async def test_works_without_context_manager(client, gateway):
    gateway.respond(
        body={
            "session_id": str(SESSION_ID),
            "status": "created",
            "created_at": "x",
            "total": 1.0,
            "currency": "RSD",
            "items": [],
        }
    )

    status = await client.check_order_status(SESSION_ID, PLATFORM_ID, SECRET)

    assert status.status == "created"
