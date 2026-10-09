"""PolakoClient.create_subscription."""

import re
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from polako.sdk import (
    BillingInterval,
    ConfigurationError,
    ConflictError,
    ForbiddenError,
    FormPost,
    HppFormPost,
    HttpClientError,
    HttpRequestError,
    PolakoClient,
    RateLimitedError,
    RedirectForm,
    RequestValidationError,
    ServerError,
    SubscriptionCreated,
    UnauthorizedError,
    UnknownRegistrationFormError,
)
from tests.factories import (
    make_form_post_response,
    make_hpp_form_response,
    make_idempotency_key,
    make_redirect_form_response,
    make_subscribe_args,
    make_subscribe_response,
)
from tests.generators import generate_readable_string

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


async def create(gateway, client, response=None, **overrides):
    """Answer 201 and create a subscription with random valid arguments; return (result, arguments)."""
    args = make_subscribe_args(**overrides)
    gateway.respond(status=201, body=response or make_subscribe_response())
    async with client:
        return await client.create_subscription(**args), args


@pytest.mark.asyncio
async def test_request_goes_to_the_company_subscriptions_endpoint(gateway, subscription_client, credentials):
    await create(gateway, subscription_client)

    request = gateway.last
    assert request.method == "POST"
    assert request.url.host == "stg-api.infra.polako-finance.com"
    assert request.url.path == f"/v1/company/{credentials.company_id}/subscriptions"


@pytest.mark.asyncio
async def test_headers_carry_the_api_key_and_the_idempotency_key(gateway, subscription_client, credentials):
    key = make_idempotency_key()

    await create(gateway, subscription_client, idempotency_key=key)

    assert gateway.last.headers["company_api_key"] == credentials.api_key
    assert gateway.last.headers["Idempotency-Key"] == key
    assert gateway.last.headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_body_is_camel_case_json(gateway, subscription_client):
    _, args = await create(gateway, subscription_client)

    assert gateway.last_json() == {
        "customerEmail": args["customer_email"],
        "amount": str(args["amount"]),
        "currency": args["currency"],
        "billingInterval": args["billing_interval"].value,
        "merchantSubscriptionRef": args["merchant_subscription_ref"],
        "successUrl": args["success_url"],
        "cancelUrl": args["cancel_url"],
        "errorUrl": args["error_url"],
    }


@pytest.mark.asyncio
async def test_the_api_key_header_is_only_sent_on_subscription_calls(gateway, subscription_client):
    gateway.respond(
        body={"session_id": str(uuid4()), "status": "created", "created_at": "x", "total": 1.0, "currency": "RSD", "items": []}
    )

    async with subscription_client as client:
        await client.check_order_status(uuid4(), uuid4(), generate_readable_string(16))

    assert "company_api_key" not in gateway.last.headers
    assert "Idempotency-Key" not in gateway.last.headers


@pytest.mark.asyncio
async def test_result_carries_the_id_the_form_and_the_used_key(gateway, subscription_client):
    key = make_idempotency_key()
    response = make_subscribe_response()

    created, _ = await create(gateway, subscription_client, response=response, idempotency_key=key)

    assert isinstance(created, SubscriptionCreated)
    assert created.subscription_id == UUID(response["subscriptionId"])
    assert isinstance(created.registration_form, FormPost)
    assert created.idempotency_key == key


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "make_form, expected",
    [(make_form_post_response, FormPost), (make_hpp_form_response, HppFormPost), (make_redirect_form_response, RedirectForm)],
)
async def test_every_form_type_comes_back_as_its_class(gateway, subscription_client, make_form, expected):
    created, _ = await create(gateway, subscription_client, response=make_subscribe_response(make_form()))

    assert isinstance(created.registration_form, expected)


@pytest.mark.asyncio
async def test_a_key_is_generated_and_returned_when_none_is_given(gateway, subscription_client):
    created, _ = await create(gateway, subscription_client)

    assert UUID_V4.match(created.idempotency_key)
    assert gateway.last.headers["Idempotency-Key"] == created.idempotency_key


@pytest.mark.asyncio
async def test_generated_keys_differ_between_calls(gateway, subscription_client):
    first, _ = await create(gateway, subscription_client)
    second, _ = await create(gateway, subscription_client)

    assert first.idempotency_key != second.idempotency_key


@pytest.mark.asyncio
async def test_retry_reuses_the_generated_key_and_the_body(gateway, sleeps, subscription_client):
    gateway.sequence({"status": 503}, {"status": 201, "body": make_subscribe_response()})

    async with subscription_client as client:
        created = await client.create_subscription(**make_subscribe_args())

    assert len(gateway.requests) == 2
    assert {r.headers["Idempotency-Key"] for r in gateway.requests} == {created.idempotency_key}
    assert len({r.content for r in gateway.requests}) == 1
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_retry_after_a_network_error_succeeds(gateway, sleeps, subscription_client):
    response = make_subscribe_response()
    gateway.sequence(httpx.ConnectError("boom"), {"status": 201, "body": response})

    async with subscription_client as client:
        created = await client.create_subscription(**make_subscribe_args(), idempotency_key=make_idempotency_key())

    assert created.subscription_id == UUID(response["subscriptionId"])
    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_repeating_a_call_with_the_same_key_sends_the_same_key(gateway, credentials):
    key = make_idempotency_key()
    response = make_subscribe_response()
    args = make_subscribe_args()
    gateway.respond(status=201, body=response)

    results = []
    for _ in range(2):
        async with PolakoClient(test_env=True, company_id=credentials.company_id, api_key=credentials.api_key) as client:
            results.append(await client.create_subscription(**args, idempotency_key=key))

    assert results[0].subscription_id == results[1].subscription_id
    assert [r.headers["Idempotency-Key"] for r in gateway.requests] == [key, key]


@pytest.mark.asyncio
async def test_persistent_server_error_gives_up_after_the_bounded_attempts(gateway, sleeps, subscription_client):
    gateway.respond(status=502, text='{"detail": "provider rejected"}')

    async with subscription_client as client:
        with pytest.raises(ServerError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert exc.value.status_code == 502
    assert len(gateway.requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, expected",
    [(401, UnauthorizedError), (403, ForbiddenError), (409, ConflictError), (422, RequestValidationError)],
)
async def test_client_errors_are_raised_without_retries(gateway, sleeps, subscription_client, status, expected):
    gateway.respond(status=status, text='{"detail": "nope"}')

    async with subscription_client as client:
        with pytest.raises(expected):
            await client.create_subscription(**make_subscribe_args())

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_a_long_rate_limit_is_reported_with_retry_after(gateway, sleeps, subscription_client):
    gateway.respond(status=429, headers={"Retry-After": "60"})

    async with subscription_client as client:
        with pytest.raises(RateLimitedError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert exc.value.retry_after == 60.0
    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_network_failure_is_a_client_error(gateway, sleeps, subscription_client):
    gateway.fail(httpx.ConnectError("boom"))

    async with subscription_client as client:
        with pytest.raises(HttpClientError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert not isinstance(exc.value, HttpRequestError)


@pytest.mark.asyncio
async def test_unknown_form_type_in_the_response_is_a_clear_error(gateway, subscription_client):
    unknown = "qr_" + generate_readable_string(5)
    gateway.respond(status=201, body=make_subscribe_response(make_redirect_form_response(type=unknown)))

    async with subscription_client as client:
        with pytest.raises(HttpRequestError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert unknown in str(exc.value)
    assert isinstance(exc.value.__cause__, UnknownRegistrationFormError)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["company_id", "api_key"])
async def test_missing_configuration_fails_before_any_request(gateway, credentials, missing):
    client = PolakoClient(test_env=True, **{**credentials._asdict(), missing: None})

    async with client:
        with pytest.raises(ConfigurationError, match=missing):
            await client.create_subscription(**make_subscribe_args())

    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": Decimal("0")},
        {"amount": Decimal("9.999")},
        {"customer_email": ""},
        {"success_url": "ftp://x"},
        {"billing_interval": "fortnightly"},
        {"idempotency_key": ""},
    ],
)
async def test_invalid_arguments_fail_before_any_request(gateway, subscription_client, overrides):
    async with subscription_client as client:
        with pytest.raises(ValueError):
            await client.create_subscription(**make_subscribe_args(**overrides))

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_billing_interval_may_be_given_as_its_string_value(gateway, subscription_client):
    interval = BillingInterval.QUARTERLY

    await create(gateway, subscription_client, billing_interval=interval.value)

    assert gateway.last_json()["billingInterval"] == interval.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount, sent",
    [(Decimal("990.00"), "990.00"), (Decimal("990"), "990"), (Decimal("1E+3"), "1000"), (Decimal("0.50"), "0.50")],
)
async def test_amount_is_sent_as_a_plain_decimal_string(gateway, subscription_client, amount, sent):
    await create(gateway, subscription_client, amount=amount)

    assert gateway.last_json()["amount"] == sent


@pytest.mark.asyncio
async def test_the_api_key_stays_out_of_repr_and_errors(gateway, subscription_client, credentials):
    assert credentials.api_key not in repr(subscription_client)
    assert str(credentials.company_id) in repr(subscription_client)

    gateway.respond(status=401, text='{"detail": "Client platform not found for the provided API key."}')
    async with subscription_client as client:
        with pytest.raises(UnauthorizedError) as exc:
            await client.create_subscription(**make_subscribe_args())

    for text in (str(exc.value), repr(exc.value), exc.value.message, exc.value.response_body or ""):
        assert credentials.api_key not in text


@pytest.mark.asyncio
async def test_a_malformed_success_body_is_a_request_error(gateway, subscription_client):
    gateway.respond(status=201, text="not json")

    async with subscription_client as client:
        with pytest.raises(HttpRequestError):
            await client.create_subscription(**make_subscribe_args())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broken",
    [
        {},
        {"registrationForm": make_redirect_form_response()},
        {**make_subscribe_response(), "subscriptionId": None},
        {**make_subscribe_response(), "subscriptionId": "not-a-uuid"},
        {"subscriptionId": str(uuid4())},
        {**make_subscribe_response(), "registrationForm": None},
    ],
    ids=["nothing", "no-id", "null-id", "bad-id", "no-form", "null-form"],
)
async def test_an_answer_without_an_id_or_a_form_is_a_request_error_at_once(gateway, subscription_client, broken):
    gateway.respond(status=201, body=broken)

    with pytest.raises(HttpRequestError) as caught:
        async with subscription_client:
            await subscription_client.create_subscription(**make_subscribe_args())

    assert isinstance(caught.value.__cause__, ValueError)
