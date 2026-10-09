"""PolakoClient.get_subscription and PolakoClient.list_subscriptions."""

from typing import Any, Awaitable, Callable, Dict, NamedTuple
from uuid import uuid4

import httpx
import pytest

from polako.sdk import (
    BillingInterval,
    ConfigurationError,
    HttpClientError,
    HttpRequestError,
    NotFoundError,
    PolakoClient,
    SubscriptionDetails,
    SubscriptionPage,
    SubscriptionStatus,
    SubscriptionSummary,
)
from tests.error_cases import STATUS_ERRORS
from tests.factories import make_credentials, make_subscription_detail_payload, make_subscription_page_payload
from tests.generators import generate_aware_datetime, generate_readable_string, generate_recent_date


class Call(NamedTuple):
    """One of the two read calls, with the kind of answer it expects and the path it uses."""

    name: str
    invoke: Callable[[PolakoClient], Awaitable[Any]]
    good_body: Callable[[], Dict[str, Any]]
    path_tail: str
    required_field: str


SUBSCRIPTION_ID = uuid4()

GET = Call(
    "get",
    lambda client: client.get_subscription(SUBSCRIPTION_ID),
    lambda: make_subscription_detail_payload(id=str(SUBSCRIPTION_ID)),
    f"/{SUBSCRIPTION_ID}",
    "id",
)
LIST = Call("list", lambda client: client.list_subscriptions(), lambda: make_subscription_page_payload(), "", "items")
CALLS = [pytest.param(GET, id="get"), pytest.param(LIST, id="list")]


async def run(gateway, client, call: Call, status: int = 200, body=None, **respond):
    gateway.respond(status=status, body=body if body is not None else call.good_body(), **respond)
    async with client:
        return await call.invoke(client)


# ---------------------------------------------------------------------------
# What both calls have in common
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
async def test_it_is_a_get_with_the_api_key_and_nothing_else_signed(gateway, subscription_client, credentials, call):
    await run(gateway, subscription_client, call)

    request = gateway.last
    assert request.method == "GET"
    assert request.url.host == "stg-api.infra.polako-finance.com"
    assert request.url.path == f"/v1/company/{credentials.company_id}/subscriptions{call.path_tail}"
    assert request.headers["company_api_key"] == credentials.api_key
    assert "Idempotency-Key" not in request.headers
    assert request.content == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("missing", ["company_id", "api_key"])
async def test_a_client_without_company_id_or_api_key_is_refused_before_any_request(gateway, call, missing):
    credentials = make_credentials()
    arguments = {"company_id": credentials.company_id, "api_key": credentials.api_key}
    arguments.pop(missing)
    client = PolakoClient(test_env=True, **arguments)

    with pytest.raises(ConfigurationError, match=missing):
        async with client:
            await call.invoke(client)

    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("status, expected", STATUS_ERRORS)
async def test_each_failure_status_is_its_own_error(gateway, subscription_client, call, status, expected):
    detail = generate_readable_string(12)

    with pytest.raises(expected) as caught:
        await run(gateway, subscription_client, call, status=status, body={"detail": detail})

    assert type(caught.value) is expected
    assert caught.value.status_code == status
    assert detail in caught.value.response_body


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
async def test_the_api_key_never_appears_in_an_error(gateway, subscription_client, credentials, call):
    with pytest.raises(NotFoundError) as caught:
        await run(gateway, subscription_client, call, status=404, body={"detail": "no"})

    assert credentials.api_key not in str(caught.value) and credentials.api_key not in repr(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_a_failed_read_is_not_retried(gateway, sleeps, subscription_client, call, status):
    gateway.sequence({"status": status, "body": {}, "headers": {"Retry-After": "1"}}, {"status": 200, "body": call.good_body()})

    with pytest.raises(HttpRequestError):
        async with subscription_client:
            await call.invoke(subscription_client)

    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
async def test_a_network_error_is_not_retried(gateway, sleeps, subscription_client, call):
    gateway.fail(httpx.ConnectError(generate_readable_string(8)))

    with pytest.raises(HttpClientError):
        async with subscription_client:
            await call.invoke(subscription_client)

    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
async def test_a_malformed_answer_is_a_request_error_with_the_reason_as_its_cause(gateway, subscription_client, call):
    body = call.good_body()
    body.pop(call.required_field)

    with pytest.raises(HttpRequestError) as caught:
        await run(gateway, subscription_client, call, body=body)

    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.asyncio
@pytest.mark.parametrize("call", CALLS)
async def test_an_answer_that_is_not_json_is_a_request_error(gateway, subscription_client, call):
    with pytest.raises(HttpRequestError):
        await run(gateway, subscription_client, call, text=generate_readable_string(20))


# ---------------------------------------------------------------------------
# get_subscription
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_the_decoded_detail(gateway, subscription_client):
    payload = make_subscription_detail_payload(id=str(SUBSCRIPTION_ID))

    detail = await run(gateway, subscription_client, GET, body=payload)

    assert isinstance(detail, SubscriptionDetails)
    assert detail.id == SUBSCRIPTION_ID
    assert str(detail.customer.id) == payload["customer"]["id"]
    assert len(detail.charge_history) == len(payload["chargeHistory"])


@pytest.mark.asyncio
@pytest.mark.parametrize("form", [str, lambda value: str(value).upper(), lambda value: value.hex, lambda value: value])
async def test_get_takes_the_id_as_a_uuid_or_as_text_in_any_form(gateway, subscription_client, credentials, form):
    subscription_id = uuid4()
    gateway.respond(body=make_subscription_detail_payload(id=str(subscription_id)))

    async with subscription_client:
        await subscription_client.get_subscription(form(subscription_id))

    assert gateway.last.url.path == f"/v1/company/{credentials.company_id}/subscriptions/{subscription_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", 42, generate_readable_string(10)])
async def test_get_refuses_a_bad_id_before_any_request(gateway, subscription_client, bad):
    with pytest.raises(ValueError, match="subscription_id"):
        async with subscription_client:
            await subscription_client.get_subscription(bad)

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_get_has_no_query_string(gateway, subscription_client):
    await run(gateway, subscription_client, GET)

    assert gateway.last.url.query == b""


# ---------------------------------------------------------------------------
# list_subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_without_arguments_asks_for_the_first_ten(gateway, subscription_client):
    await run(gateway, subscription_client, LIST)

    assert dict(gateway.last.url.params) == {"limit": "10", "offset": "0"}


@pytest.mark.asyncio
async def test_list_sends_every_filter_under_the_servers_name(gateway, subscription_client):
    text = generate_readable_string(8)
    start = generate_recent_date()
    end = generate_aware_datetime()
    gateway.respond(body=make_subscription_page_payload())

    async with subscription_client:
        await subscription_client.list_subscriptions(
            status=[SubscriptionStatus.ACTIVE, "past_due"],
            billing_interval=BillingInterval.YEARLY,
            search=text,
            created_from=start,
            created_to=end,
            sort_by="next_charge_at",
            sort_order="asc",
            limit=40,
            offset=80,
        )

    params = gateway.last.url.params
    assert params.get_list("status") == ["active", "past_due"]
    assert params.get_list("billing_interval") == ["yearly"]
    assert params["filter"] == text
    assert params["date_from"] == start.isoformat()
    assert params["date_to"].endswith("Z") and "." not in params["date_to"]
    assert (params["sort_by"], params["sort_order"], params["limit"], params["offset"]) == ("next_charge_at", "asc", "40", "80")


@pytest.mark.asyncio
async def test_list_returns_a_page_of_decoded_summaries(gateway, subscription_client):
    payload = make_subscription_page_payload(count=3, total=17, page_size=10)
    gateway.respond(body=payload)

    async with subscription_client:
        page = await subscription_client.list_subscriptions(limit=10, offset=20)

    assert isinstance(page, SubscriptionPage)
    assert isinstance(page.items, tuple) and all(isinstance(item, SubscriptionSummary) for item in page.items)
    assert [str(item.id) for item in page.items] == [item["id"] for item in payload["items"]]
    assert (page.total, page.limit, page.offset) == (17, 10, 20)


@pytest.mark.asyncio
async def test_list_takes_the_page_size_from_the_answer_and_the_offset_from_the_request(gateway, subscription_client):
    gateway.respond(body=make_subscription_page_payload(count=1, total=1, page_size=7))

    async with subscription_client:
        page = await subscription_client.list_subscriptions(limit=50, offset=3)

    assert (page.limit, page.offset) == (7, 3)


@pytest.mark.asyncio
async def test_list_of_nothing_is_an_empty_page(gateway, subscription_client):
    gateway.respond(body=make_subscription_page_payload(count=0, total=0))

    async with subscription_client:
        page = await subscription_client.list_subscriptions()

    assert page.items == () and page.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"status": "nope"},
        {"status": []},
        {"billing_interval": ["hourly"]},
        {"search": "   "},
        {"sort_by": "id"},
        {"sort_order": "up"},
        {"created_from": generate_recent_date().isoformat()},
        {"created_to": 5},
    ],
    ids=lambda arguments: next(iter(arguments)) + "=" + repr(next(iter(arguments.values())))[:14],
)
async def test_list_refuses_a_bad_argument_before_any_request(gateway, subscription_client, arguments):
    with pytest.raises(ValueError, match=next(iter(arguments))):
        async with subscription_client:
            await subscription_client.list_subscriptions(**arguments)

    assert gateway.requests == []


@pytest.mark.asyncio
async def test_list_takes_its_arguments_by_keyword_only(gateway, subscription_client):
    with pytest.raises(TypeError):
        async with subscription_client:
            await subscription_client.list_subscriptions(SubscriptionStatus.ACTIVE)  # type: ignore[misc]


@pytest.mark.asyncio
async def test_the_order_of_the_keyword_arguments_does_not_matter(gateway, subscription_client):
    gateway.respond(body=make_subscription_page_payload())

    async with subscription_client:
        await subscription_client.list_subscriptions(status=["paused", "active"], limit=5)
        first = sorted(gateway.last.url.params.multi_items())
        await subscription_client.list_subscriptions(limit=5, status=["paused", "active"])
        second = sorted(gateway.last.url.params.multi_items())

    assert first == second
