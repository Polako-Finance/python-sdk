"""PolakoClient.pause_subscription, resume_subscription and cancel_subscription."""

from uuid import uuid4

import httpx
import pytest

from polako.sdk import (
    ConfigurationError,
    ConflictError,
    HttpClientError,
    HttpRequestError,
    PolakoClient,
)
from tests.error_cases import STATUS_ERRORS
from tests.factories import make_credentials
from tests.generators import generate_readable_string

ACTIONS = ["pause", "resume", "cancel"]
EVERY_ACTION = pytest.mark.parametrize("action", ACTIONS)


async def change(gateway, client, action, subscription_id=None, status=204, **respond):
    """Answer `status` and call the method; return what it returned."""
    gateway.respond(status=status, **respond)
    async with client:
        return await getattr(client, f"{action}_subscription")(subscription_id or uuid4())


@pytest.mark.asyncio
@EVERY_ACTION
async def test_it_is_a_patch_to_the_subscription_with_the_api_key(gateway, subscription_client, credentials, action):
    subscription_id = uuid4()

    await change(gateway, subscription_client, action, subscription_id)

    request = gateway.last
    assert request.method == "PATCH"
    assert request.url.host == "stg-api.infra.polako-finance.com"
    assert request.url.path == f"/v1/company/{credentials.company_id}/subscriptions/{subscription_id}/{action}"
    assert request.headers["company_api_key"] == credentials.api_key


@pytest.mark.asyncio
@EVERY_ACTION
async def test_nothing_else_is_sent(gateway, subscription_client, action):
    await change(gateway, subscription_client, action)

    request = gateway.last
    assert request.content == b""
    assert request.url.query == b""
    assert "Idempotency-Key" not in request.headers


@pytest.mark.asyncio
@EVERY_ACTION
async def test_success_returns_nothing(gateway, subscription_client, action):
    assert await change(gateway, subscription_client, action) is None


@pytest.mark.asyncio
@EVERY_ACTION
async def test_a_success_with_a_body_is_still_nothing(gateway, subscription_client, action):
    result = await change(gateway, subscription_client, action, status=200, body={generate_readable_string(5): 1})

    assert result is None


@pytest.mark.asyncio
@EVERY_ACTION
@pytest.mark.parametrize("form", [str, lambda value: str(value).upper(), lambda value: value.hex, lambda value: value])
async def test_the_id_is_a_uuid_or_text_in_any_form(gateway, subscription_client, credentials, action, form):
    subscription_id = uuid4()

    await change(gateway, subscription_client, action, form(subscription_id))

    assert gateway.last.url.path == f"/v1/company/{credentials.company_id}/subscriptions/{subscription_id}/{action}"


@pytest.mark.asyncio
@EVERY_ACTION
@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", 42, generate_readable_string(10)])
async def test_a_bad_id_is_refused_before_any_request(gateway, subscription_client, action, bad):
    with pytest.raises(ValueError, match="subscription_id"):
        async with subscription_client:
            await getattr(subscription_client, f"{action}_subscription")(bad)

    assert gateway.requests == []


@pytest.mark.asyncio
@EVERY_ACTION
@pytest.mark.parametrize("missing", ["company_id", "api_key"])
async def test_a_client_without_company_id_or_api_key_is_refused_before_any_request(gateway, action, missing):
    credentials = make_credentials()
    arguments = {"company_id": credentials.company_id, "api_key": credentials.api_key}
    arguments.pop(missing)
    client = PolakoClient(test_env=True, **arguments)

    with pytest.raises(ConfigurationError, match=missing):
        async with client:
            await getattr(client, f"{action}_subscription")(uuid4())

    assert gateway.requests == []


@pytest.mark.asyncio
@EVERY_ACTION
@pytest.mark.parametrize("status, expected", STATUS_ERRORS)
async def test_each_failure_status_is_its_own_error_with_the_servers_reason(
    gateway, subscription_client, action, status, expected
):
    reason = generate_readable_string(14)

    with pytest.raises(expected) as caught:
        await change(gateway, subscription_client, action, status=status, body={"detail": reason})

    assert type(caught.value) is expected
    assert caught.value.status_code == status
    assert reason in caught.value.response_body and reason in str(caught.value)


@pytest.mark.asyncio
@EVERY_ACTION
async def test_the_api_key_never_appears_in_an_error(gateway, subscription_client, credentials, action):
    with pytest.raises(ConflictError) as caught:
        await change(gateway, subscription_client, action, status=409, body={"detail": "no"})

    assert credentials.api_key not in str(caught.value) and credentials.api_key not in repr(caught.value)


@pytest.mark.asyncio
@EVERY_ACTION
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_a_failed_change_is_not_repeated(gateway, sleeps, subscription_client, action, status):
    gateway.sequence({"status": status, "body": {}, "headers": {"Retry-After": "1"}}, {"status": 204})

    with pytest.raises(HttpRequestError):
        async with subscription_client:
            await getattr(subscription_client, f"{action}_subscription")(uuid4())

    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
@EVERY_ACTION
async def test_a_network_error_is_not_repeated_and_is_a_client_error_not_a_refusal(
    gateway, sleeps, subscription_client, action
):
    gateway.fail(httpx.ReadTimeout(generate_readable_string(8)))

    with pytest.raises(HttpClientError) as caught:
        async with subscription_client:
            await getattr(subscription_client, f"{action}_subscription")(uuid4())

    assert not isinstance(caught.value, HttpRequestError)
    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_the_three_calls_go_to_three_different_paths(gateway, subscription_client):
    subscription_id = uuid4()
    paths = []
    for action in ACTIONS:
        await change(gateway, subscription_client, action, subscription_id)
        paths.append(gateway.last.url.path.rsplit("/", 1)[-1])

    assert paths == ACTIONS
