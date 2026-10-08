"""The transport retries only requests that carry an Idempotency-Key."""

import httpx
import pytest

from polako.sdk import (
    ConflictError,
    HttpClientError,
    HttpRequestError,
    RateLimitedError,
    ServerError,
    UnauthorizedError,
)
from polako.sdk._async_client import AsyncHttpClient
from tests.factories import make_idempotency_key, make_order_status_response
from tests.generators import generate_random_host, generate_readable_string


@pytest.fixture
def key() -> str:
    return make_idempotency_key()


@pytest.fixture
def keyed(key) -> dict:
    return {"Idempotency-Key": key}


@pytest.fixture
def success() -> dict:
    return {"status": 200, "body": make_order_status_response()}


def http_client(**kwargs):
    return AsyncHttpClient(f"https://{generate_random_host()}", **kwargs)


async def post(headers=None):
    async with http_client() as http:
        return await http.post("/v1/anything", request_body={generate_readable_string(6): 1}, headers=headers)


@pytest.mark.asyncio
async def test_request_without_key_is_sent_once_on_server_error(gateway, sleeps):
    gateway.respond(status=500)

    with pytest.raises(ServerError):
        await post()

    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_request_without_key_is_sent_once_on_network_error(gateway, sleeps):
    gateway.fail(httpx.ConnectError(generate_readable_string(8)))

    with pytest.raises(HttpClientError):
        await post()

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_get_without_key_is_not_retried(gateway, sleeps):
    gateway.respond(status=503)

    async with http_client() as http:
        with pytest.raises(ServerError):
            await http.get("/v1/anything")

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_keyed_request_is_retried_until_it_succeeds(gateway, sleeps, keyed, success):
    gateway.sequence({"status": 500}, {"status": 502}, success)

    await post(keyed)

    assert len(gateway.requests) == 3


@pytest.mark.asyncio
async def test_every_attempt_carries_the_same_key_and_the_same_body(gateway, sleeps, keyed, key, success):
    gateway.sequence({"status": 503}, {"status": 503}, success)

    await post(keyed)

    assert {r.headers["Idempotency-Key"] for r in gateway.requests} == {key}
    assert len({r.content for r in gateway.requests}) == 1


@pytest.mark.asyncio
async def test_key_header_is_recognised_case_insensitively(gateway, sleeps, key, success):
    gateway.sequence({"status": 500}, success)

    await post({"idempotency-key": key})

    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_attempts_are_bounded_and_the_last_error_is_raised(gateway, sleeps, keyed):
    gateway.respond(status=503)

    with pytest.raises(ServerError):
        await post(keyed)

    assert len(gateway.requests) == 3
    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_max_attempts_is_configurable(gateway, sleeps, keyed):
    gateway.respond(status=503)

    async with http_client(max_attempts=5) as http:
        with pytest.raises(ServerError):
            await http.post("/v1/anything", request_body={}, headers=keyed)

    assert len(gateway.requests) == 5


@pytest.mark.asyncio
async def test_network_error_is_retried_with_a_key(gateway, sleeps, keyed, success):
    gateway.sequence(httpx.ConnectError(generate_readable_string(8)), httpx.ReadTimeout(generate_readable_string(8)), success)

    await post(keyed)

    assert len(gateway.requests) == 3


@pytest.mark.asyncio
async def test_persistent_network_error_raises_client_error_not_request_error(gateway, sleeps, keyed):
    gateway.fail(httpx.ConnectError(generate_readable_string(8)))

    with pytest.raises(HttpClientError) as exc:
        await post(keyed)

    assert not isinstance(exc.value, HttpRequestError)
    assert len(gateway.requests) == 3


@pytest.mark.asyncio
async def test_backoff_is_exponential_and_capped(gateway, sleeps, keyed):
    gateway.respond(status=500)

    async with http_client(max_attempts=6, retry_base_delay=1.0, retry_max_delay=4.0) as http:
        with pytest.raises(ServerError):
            await http.post("/v1/anything", request_body={}, headers=keyed)

    assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]


@pytest.mark.asyncio
async def test_rate_limit_honours_retry_after(gateway, sleeps, keyed, success):
    gateway.sequence({"status": 429, "headers": {"Retry-After": "2"}}, success)

    await post(keyed)

    assert sleeps == [2.0]
    assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_rate_limit_waits_at_least_the_backoff(gateway, sleeps, keyed, success):
    gateway.sequence({"status": 429, "headers": {"Retry-After": "0"}}, success)

    async with http_client(retry_base_delay=0.5) as http:
        await http.post("/v1/anything", request_body={}, headers=keyed)

    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_retry_after_longer_than_the_cap_is_not_waited_for(gateway, sleeps, keyed):
    gateway.respond(status=429, headers={"Retry-After": "60"})

    with pytest.raises(RateLimitedError) as exc:
        await post(keyed)

    assert exc.value.retry_after == 60.0
    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 410, 422])
async def test_client_errors_are_never_retried(gateway, sleeps, keyed, status):
    gateway.respond(status=status)

    with pytest.raises(HttpRequestError):
        await post(keyed)

    assert len(gateway.requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_errors_keep_their_class_through_retries(gateway, sleeps, keyed):
    gateway.respond(status=401)
    with pytest.raises(UnauthorizedError):
        await post(keyed)

    gateway.respond(status=409)
    with pytest.raises(ConflictError):
        await post(keyed)


@pytest.mark.asyncio
async def test_unparseable_success_body_is_not_retried(gateway, sleeps, keyed):
    gateway.respond(text=generate_readable_string(12))

    class Model:
        @staticmethod
        def from_json(text):
            raise ValueError(generate_readable_string(8))

    async with http_client() as http:
        with pytest.raises(HttpRequestError):
            await http.post("/v1/anything", request_body={}, response_model=Model, headers=keyed)  # type: ignore[type-var]

    assert len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_payment_methods_are_never_retried(client, gateway, sleeps, platform):
    from uuid import uuid4

    gateway.respond(status=500)

    async with client:
        with pytest.raises(ServerError):
            await client.refund_session(uuid4(), platform.platform_id, platform.secret_key, generate_readable_string(20))
        with pytest.raises(ServerError):
            await client.check_order_status(uuid4(), platform.platform_id, platform.secret_key)

    assert len(gateway.requests) == 2
    assert sleeps == []
