"""Creating a subscription over real HTTP against the gateway emulator."""

import json
from uuid import UUID, uuid4

import httpx
import pytest

from polako.sdk import (
    BillingInterval,
    ConflictError,
    ForbiddenError,
    FormPost,
    HppFormPost,
    PolakoClient,
    RedirectForm,
    RequestValidationError,
    UnauthorizedError,
)
from tests.factories import make_idempotency_key, make_subscribe_args
from tests.generators import generate_api_key, generate_readable_string


def wire_body(args: dict) -> dict:
    """What the merchant's arguments look like on the wire."""
    return {
        "customerEmail": args["customer_email"],
        "amount": str(args["amount"]),
        "currency": args["currency"],
        "billingInterval": args["billing_interval"].value,
        "merchantSubscriptionRef": args["merchant_subscription_ref"],
        "successUrl": args["success_url"],
        "cancelUrl": args["cancel_url"],
        "errorUrl": args["error_url"],
    }


async def post_raw(server, platform, body, headers=None, company_id=None):
    """A request the SDK would not make: the caller controls every header and the body."""
    headers = {"company_api_key": platform.api_key, "Idempotency-Key": make_idempotency_key(), **(headers or {})}
    async with httpx.AsyncClient() as http:
        return await http.post(
            f"{server.base_url}/v1/company/{company_id or platform.company_id}/subscriptions", json=body, headers=headers
        )


@pytest.mark.asyncio
async def test_a_subscription_is_created_through_the_sdk(gateway_server, registered_platform, merchant_client):
    args = make_subscribe_args()
    key = make_idempotency_key()

    async with merchant_client as client:
        created = await client.create_subscription(**args, idempotency_key=key)

    assert isinstance(created.subscription_id, UUID)
    assert isinstance(created.registration_form, FormPost)
    assert created.idempotency_key == key
    [received] = gateway_server.received_requests
    assert received.method == "POST"
    assert received.path == f"/v1/company/{registered_platform.company_id}/subscriptions"
    assert received.headers["company_api_key"] == registered_platform.api_key
    assert received.headers["Idempotency-Key"] == key
    assert json.loads(received.body) == wire_body(args)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "form_type, expected",
    [("form_post", FormPost), ("hpp_form_post", HppFormPost), ("iframe", RedirectForm)],
)
async def test_every_kind_of_registration_form_reaches_the_sdk(gateway_server, merchant_client, form_type, expected):
    gateway_server.form_type = form_type

    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args())

    assert isinstance(created.registration_form, expected)


@pytest.mark.asyncio
async def test_repeating_a_request_with_the_same_key_returns_the_same_subscription(gateway_server, merchant_client):
    args = make_subscribe_args()
    key = make_idempotency_key()

    async with merchant_client as client:
        first = await client.create_subscription(**args, idempotency_key=key)
        second = await client.create_subscription(**args, idempotency_key=key)

    assert first.subscription_id == second.subscription_id
    assert first.registration_form == second.registration_form
    assert len(gateway_server.subscriptions) == 1


@pytest.mark.asyncio
async def test_another_key_makes_another_subscription_while_none_is_live(gateway_server, merchant_client):
    args = make_subscribe_args()

    async with merchant_client as client:
        first = await client.create_subscription(**args, idempotency_key=make_idempotency_key())
        second = await client.create_subscription(**args, idempotency_key=make_idempotency_key())

    assert first.subscription_id != second.subscription_id
    assert len(gateway_server.subscriptions) == 2


@pytest.mark.asyncio
async def test_an_unknown_api_key_is_unauthorized(gateway_server, registered_platform):
    client = PolakoClient(test_env=True, company_id=registered_platform.company_id, api_key=generate_api_key())

    async with client:
        with pytest.raises(UnauthorizedError):
            await client.create_subscription(**make_subscribe_args())


@pytest.mark.asyncio
async def test_a_key_of_another_company_is_forbidden(gateway_server, registered_platform):
    client = PolakoClient(test_env=True, company_id=uuid4(), api_key=registered_platform.api_key)

    async with client:
        with pytest.raises(ForbiddenError):
            await client.create_subscription(**make_subscribe_args())


@pytest.mark.asyncio
async def test_subscriptions_switched_off_for_the_company_is_a_conflict(gateway_server, registered_platform):
    gateway_server.subscriptions_enabled = False
    client = PolakoClient(test_env=True, company_id=registered_platform.company_id, api_key=registered_platform.api_key)

    async with client:
        with pytest.raises(ConflictError):
            await client.create_subscription(**make_subscribe_args())

    assert gateway_server.subscriptions == {}


@pytest.mark.asyncio
async def test_a_currency_outside_the_platform_wide_allow_list_is_rejected(gateway_server, merchant_client):
    gateway_server.allowed_currencies = ["RSD"]

    async with merchant_client as client:
        with pytest.raises(RequestValidationError):
            await client.create_subscription(**make_subscribe_args(currency="EUR"))
        created = await client.create_subscription(**make_subscribe_args(currency="RSD"))

    assert created.subscription_id in gateway_server.subscriptions


@pytest.mark.asyncio
async def test_a_currency_the_gateway_does_not_know_is_rejected(gateway_server, merchant_client):
    async with merchant_client as client:
        with pytest.raises(RequestValidationError):
            await client.create_subscription(**make_subscribe_args(currency="XXX"))


@pytest.mark.asyncio
async def test_a_request_without_the_api_key_header_is_unauthorized(gateway_server, registered_platform):
    response = await post_raw(
        gateway_server, registered_platform, wire_body(make_subscribe_args()), headers={"company_api_key": ""}
    )

    assert response.status_code == 401
    assert "company_api_key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_request_without_an_idempotency_key_is_rejected(gateway_server, registered_platform):
    async with httpx.AsyncClient() as http:
        response = await http.post(
            f"{gateway_server.base_url}/v1/company/{registered_platform.company_id}/subscriptions",
            json=wire_body(make_subscribe_args()),
            headers={"company_api_key": registered_platform.api_key},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_gateway_also_accepts_snake_case_names(gateway_server, registered_platform):
    args = make_subscribe_args()
    snake = {
        "customer_email": args["customer_email"],
        "amount": str(args["amount"]),
        "currency": args["currency"],
        "billing_interval": args["billing_interval"].value,
        "merchant_subscription_ref": args["merchant_subscription_ref"],
        "success_url": args["success_url"],
        "cancel_url": args["cancel_url"],
        "error_url": args["error_url"],
    }

    response = await post_raw(gateway_server, registered_platform, snake)

    assert response.status_code == 201
    assert UUID(response.json()["subscriptionId"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"customerEmail": "not-an-email"},
        {"amount": "0"},
        {"amount": "-5"},
        {"amount": "abc"},
        {"billingInterval": "fortnightly"},
        {"merchantSubscriptionRef": ""},
        {"merchantSubscriptionRef": "x" * 129},
        {"successUrl": "ftp://shop.example.com/ok"},
        {"cancelUrl": "not a url"},
        {"errorUrl": "javascript:alert(1)"},
        {"currency": "xx"},
    ],
)
async def test_an_invalid_field_is_rejected(gateway_server, registered_platform, change):
    response = await post_raw(gateway_server, registered_platform, {**wire_body(make_subscribe_args()), **change})

    assert response.status_code == 422
    assert gateway_server.subscriptions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing",
    [
        "customerEmail",
        "amount",
        "currency",
        "billingInterval",
        "merchantSubscriptionRef",
        "successUrl",
        "cancelUrl",
        "errorUrl",
    ],
)
async def test_a_missing_field_is_rejected(gateway_server, registered_platform, missing):
    body = wire_body(make_subscribe_args())
    del body[missing]

    response = await post_raw(gateway_server, registered_platform, body)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_is_rejected(gateway_server, registered_platform):
    async with httpx.AsyncClient() as http:
        response = await http.post(
            f"{gateway_server.base_url}/v1/company/{registered_platform.company_id}/subscriptions",
            content=generate_readable_string(20),
            headers={"company_api_key": registered_platform.api_key, "Idempotency-Key": make_idempotency_key()},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_company_id_that_is_not_a_uuid_is_rejected(gateway_server, registered_platform):
    response = await post_raw(
        gateway_server, registered_platform, wire_body(make_subscribe_args()), company_id=generate_readable_string(8)
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_every_request_is_recorded_as_it_arrived(gateway_server, registered_platform):
    key = make_idempotency_key()
    body = wire_body(make_subscribe_args())

    await post_raw(gateway_server, registered_platform, body, headers={"Idempotency-Key": key})

    [received] = gateway_server.received_requests
    assert received.headers["Idempotency-Key"] == key
    assert json.loads(received.body) == body


def test_billing_interval_values_are_the_ones_the_emulator_accepts():
    assert {interval.value for interval in BillingInterval} == {"daily", "weekly", "monthly", "quarterly", "yearly"}
