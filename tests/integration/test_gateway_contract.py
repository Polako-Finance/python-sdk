"""What the real server answers to the read and management routes, asserted on the emulator over raw HTTP.

Every case here was observed on the real server (a live run of the SDK examples and a probe with requests the SDK never
sends). They keep the emulator honest: the end-to-end tests of the SDK are only as good as the emulator they run on.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from tests.factories import make_subscribe_args
from tests.generators import generate_api_key, generate_readable_string

ZERO_ID = "00000000-0000-4000-8000-000000000000"


@pytest_asyncio.fixture
async def http():
    async with httpx.AsyncClient(timeout=10) as client:
        yield client


@pytest_asyncio.fixture
async def active_subscription(gateway_server, merchant_client):
    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args())
    gateway_server.activate(created.subscription_id)
    return created.subscription_id


def key(registered_platform):
    return {"company_api_key": registered_platform.api_key}


def url(registered_platform, gateway_server, *tail):
    return "/".join([gateway_server.base_url, "v1", "company", str(registered_platform.company_id), "subscriptions", *tail])


# ---------------------------------------------------------------------------
# A list query that the server does not accept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params, kind, location",
    [
        ({"limit": 0}, "greater_than_equal", ["query", "limit"]),
        ({"limit": 101}, "less_than_equal", ["query", "limit"]),
        ({"limit": "abc"}, "int_parsing", ["query", "limit"]),
        ({"offset": -1}, "greater_than_equal", ["query", "offset"]),
        ({"status": "bogus"}, "enum", ["query", "status", 0]),
        ({"billing_interval": "bogus"}, "enum", ["query", "billing_interval", 0]),
    ],
    ids=["limit-0", "limit-101", "limit-text", "offset-negative", "status", "billing-interval"],
)
async def test_a_parameter_the_server_rejects_is_a_422_that_says_which_and_why(
    gateway_server, registered_platform, http, params, kind, location
):
    response = await http.get(url(registered_platform, gateway_server), params=params, headers=key(registered_platform))

    assert response.status_code == 422
    [problem] = response.json()["detail"]
    assert problem["type"] == kind and problem["loc"] == location and problem["msg"].startswith("Input should be")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params, message",
    [
        (
            {"sort_by": "bogus"},
            "Invalid sort_by 'bogus'. Allowed values: ['amount', 'created_at', 'last_charged_at', 'next_charge_at', 'status'].",
        ),
        ({"sort_order": "bogus"}, "Invalid sort_order 'bogus'. Allowed values: ['asc', 'desc']."),
        ({"sort_order": "ASC"}, "Invalid sort_order 'ASC'. Allowed values: ['asc', 'desc']."),
        (
            {"date_from": "garbage"},
            "Invalid ISO 8601 format of date_from. Expected: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS[Z|\u00b1HH:MM].",
        ),
        (
            {"date_to": "garbage"},
            "Invalid ISO 8601 format of date_to. Expected: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS[Z|\u00b1HH:MM].",
        ),
    ],
    ids=["sort-by", "sort-order", "sort-order-case", "date-from", "date-to"],
)
async def test_a_sort_or_a_date_the_server_rejects_is_a_400_with_the_reason_as_text(
    gateway_server, registered_platform, http, params, message
):
    response = await http.get(url(registered_platform, gateway_server), params=params, headers=key(registered_platform))

    assert (response.status_code, response.json()) == (400, {"detail": message})


@pytest.mark.asyncio
async def test_a_blank_search_is_not_an_error_and_matches_nothing(
    gateway_server, registered_platform, http, active_subscription
):
    response = await http.get(
        url(registered_platform, gateway_server), params={"filter": " "}, headers=key(registered_platform)
    )

    assert response.status_code == 200 and response.json()["items"] == []


# ---------------------------------------------------------------------------
# Who wins when more than one thing is wrong
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authentication_is_checked_before_the_query(gateway_server, registered_platform, http):
    base = url(registered_platform, gateway_server)

    unknown = await http.get(base, params={"limit": 0}, headers={"company_api_key": generate_api_key()})
    nobody = await http.get(base, params={"limit": 0})

    assert (unknown.status_code, unknown.json()) == (401, {"detail": "Client platform not found for the provided API key."})
    assert (nobody.status_code, nobody.json()) == (401, {"detail": "Authentication required."})


@pytest.mark.asyncio
async def test_the_key_is_checked_before_the_subscription_id_is_read(gateway_server, registered_platform, http):
    response = await http.get(
        url(registered_platform, gateway_server, "not-a-uuid"), headers={"company_api_key": generate_api_key()}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_a_malformed_id_is_a_422_with_its_place_for_a_known_key(gateway_server, registered_platform, http):
    headers = key(registered_platform)

    in_subscription = await http.get(url(registered_platform, gateway_server, "not-a-uuid"), headers=headers)
    in_company = await http.get(f"{gateway_server.base_url}/v1/company/not-a-uuid/subscriptions", headers=headers)

    assert in_subscription.status_code == in_company.status_code == 422
    assert in_subscription.json()["detail"][0]["loc"] == ["path", "subscription_id"]
    assert in_company.json()["detail"][0]["loc"] == ["path", "company_id"]
    assert in_subscription.json()["detail"][0]["type"] == "uuid_parsing"


@pytest.mark.asyncio
async def test_the_refusals_have_the_servers_words(gateway_server, registered_platform, http, active_subscription):
    outsider = gateway_server.add_platform()
    mine = url(registered_platform, gateway_server)

    other_key = await http.get(mine, headers={"company_api_key": outsider.api_key})
    unknown_id = await http.get(f"{mine}/{ZERO_ID}", headers=key(registered_platform))
    others_subscription = await http.get(
        f"{gateway_server.base_url}/v1/company/{outsider.company_id}/subscriptions/{active_subscription}",
        headers={"company_api_key": outsider.api_key},
    )

    assert (other_key.status_code, other_key.json()) == (403, {"detail": "API key does not belong to this company."})
    assert (unknown_id.status_code, unknown_id.json()) == (404, {"detail": "Subscription not found"})
    assert (others_subscription.status_code, others_subscription.json()) == (
        403,
        {"detail": "Subscription does not belong to this company"},
    )


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_change_the_status_does_not_allow_is_a_409_and_a_switch_off_is_a_409_with_its_own_words(
    gateway_server, registered_platform, http, active_subscription
):
    path = url(registered_platform, gateway_server, str(active_subscription), "resume")

    wrong_status = await http.patch(path, headers=key(registered_platform))
    gateway_server.subscriptions_enabled = False
    switched_off = await http.patch(path, headers=key(registered_platform))

    assert (wrong_status.status_code, wrong_status.json()) == (
        409,
        {"detail": "Subscription status does not allow this operation"},
    )
    assert (switched_off.status_code, switched_off.json()) == (
        409,
        {"detail": "Subscriptions are not enabled for this company"},
    )


@pytest.mark.asyncio
async def test_a_body_and_an_idempotency_key_on_a_change_are_ignored(
    gateway_server, registered_platform, http, active_subscription
):
    path = url(registered_platform, gateway_server, str(active_subscription), "pause")

    response = await http.patch(path, headers={**key(registered_platform), "Idempotency-Key": str(uuid4())}, json={"x": 1})

    assert response.status_code == 204 and response.content == b""
    assert gateway_server.subscriptions[active_subscription].status == "paused"


@pytest.mark.asyncio
async def test_a_change_of_an_unknown_subscription_is_a_404_and_without_a_key_a_401(gateway_server, registered_platform, http):
    path = url(registered_platform, gateway_server, ZERO_ID, "pause")

    unknown = await http.patch(path, headers=key(registered_platform))
    nobody = await http.patch(path)

    assert (unknown.status_code, nobody.status_code) == (404, 401)


# ---------------------------------------------------------------------------
# What a list holds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_day_as_the_upper_bound_means_the_whole_day_and_the_page_size_is_the_limit(
    gateway_server, registered_platform, http, active_subscription
):
    today = datetime.now(timezone.utc).date()
    base, headers = url(registered_platform, gateway_server), key(registered_platform)

    until_today = await http.get(base, params={"date_to": today.isoformat(), "limit": 7}, headers=headers)
    from_tomorrow = await http.get(base, params={"date_from": (today + timedelta(days=1)).isoformat()}, headers=headers)

    assert [item["id"] for item in until_today.json()["items"]] == [str(active_subscription)]
    assert until_today.json()["page_size"] == 7 and until_today.json()["total"] == 1
    assert from_tomorrow.json()["items"] == []


@pytest.mark.asyncio
async def test_a_list_answers_in_the_servers_shape(gateway_server, registered_platform, http, active_subscription):
    answer = (await http.get(url(registered_platform, gateway_server), headers=key(registered_platform))).json()

    assert set(answer) == {"items", "total", "page_size"}
    assert set(answer["items"][0]) == {
        "id",
        "customerId",
        "customerEmail",
        "merchantSubscriptionRef",
        "amount",
        "currency",
        "billingInterval",
        "status",
        "nextChargeAt",
        "lastChargedAt",
        "createdAt",
    }
    assert answer["items"][0]["lastChargedAt"] is None and answer["items"][0]["nextChargeAt"].endswith("Z")
    assert generate_readable_string(1)
