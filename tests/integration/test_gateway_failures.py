"""The SDK against a gateway that fails, over real HTTP: retries, limits, dropped connections."""

from uuid import UUID

import pytest

from polako.sdk import (
    ConflictError,
    ForbiddenError,
    HttpClientError,
    HttpRequestError,
    PolakoClient,
    RateLimitedError,
    RequestValidationError,
    ServerError,
    UnauthorizedError,
)
from tests.factories import make_idempotency_key, make_subscribe_args
from tests.generators import generate_api_key


class FakeClock:
    """Time the emulator reads, moved only by the test or by the SDK's waiting."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(gateway_server) -> FakeClock:
    fake = FakeClock()
    gateway_server.clock = fake
    return fake


@pytest.fixture
def waiting(monkeypatch, clock) -> list:
    """The SDK's wait between retries moves the emulator's clock instead of sleeping; returns the waits."""
    waits: list = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr("polako.sdk._async_client._sleep", fake_sleep)
    return waits


def keys_and_bodies(server):
    return [(r.headers["Idempotency-Key"], r.body) for r in server.received_requests]


@pytest.mark.asyncio
async def test_a_service_outage_is_retried_with_the_same_key_and_body(gateway_server, merchant_client, sleeps):
    gateway_server.fail_next(503)
    key = make_idempotency_key()

    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args(), idempotency_key=key)

    assert len(gateway_server.received_requests) == 2
    assert {k for k, _ in keys_and_bodies(gateway_server)} == {key}
    assert len({b for _, b in keys_and_bodies(gateway_server)}) == 1
    assert list(gateway_server.subscriptions) == [created.subscription_id]
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_two_failures_and_then_success_use_all_three_attempts(gateway_server, merchant_client, sleeps):
    gateway_server.fail_next(503, times=2)

    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args())

    assert len(gateway_server.received_requests) == 3
    assert isinstance(created.subscription_id, UUID)
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_a_persistent_outage_gives_up_after_three_attempts(gateway_server, merchant_client, sleeps):
    gateway_server.fail_next(503, times=10)

    async with merchant_client as client:
        with pytest.raises(ServerError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert exc.value.status_code == 503
    assert len(gateway_server.received_requests) == 3
    assert gateway_server.subscriptions == {}


@pytest.mark.asyncio
async def test_the_card_processor_refusing_is_retried_and_then_reported(gateway_server, merchant_client, sleeps):
    gateway_server.reject_registration_next(times=10)

    async with merchant_client as client:
        with pytest.raises(ServerError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert exc.value.status_code == 502
    assert len(gateway_server.received_requests) == 3
    assert gateway_server.subscriptions == {}


@pytest.mark.asyncio
async def test_a_refused_request_can_be_repeated_with_the_same_key_once_the_processor_recovers(
    gateway_server, merchant_client, sleeps
):
    gateway_server.reject_registration_next(times=3)
    args, key = make_subscribe_args(), make_idempotency_key()

    async with merchant_client as client:
        with pytest.raises(ServerError):
            await client.create_subscription(**args, idempotency_key=key)
        created = await client.create_subscription(**args, idempotency_key=key)
        again = await client.create_subscription(**args, idempotency_key=key)

    assert created.subscription_id == again.subscription_id
    assert len(gateway_server.subscriptions) == 1


@pytest.mark.asyncio
async def test_a_short_rate_limit_is_waited_out(gateway_server, merchant_client, sleeps):
    gateway_server.fail_next(429, retry_after=1)

    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args())

    assert len(gateway_server.received_requests) == 2
    assert sleeps == [1.0]
    assert created.subscription_id in gateway_server.subscriptions


@pytest.mark.asyncio
async def test_a_long_rate_limit_is_reported_without_waiting(gateway_server, merchant_client, sleeps):
    gateway_server.fail_next(429, retry_after=60)

    async with merchant_client as client:
        with pytest.raises(RateLimitedError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert exc.value.retry_after == 60.0
    assert len(gateway_server.received_requests) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_the_limit_of_requests_per_window_is_enforced(gateway_server, merchant_client, clock, sleeps):
    gateway_server.rate_limit = (2, 60)

    async with merchant_client as client:
        await client.create_subscription(**make_subscribe_args())
        await client.create_subscription(**make_subscribe_args())
        with pytest.raises(RateLimitedError) as exc:
            await client.create_subscription(**make_subscribe_args())

        assert exc.value.retry_after == 60.0
        clock.advance(61)
        await client.create_subscription(**make_subscribe_args())

    assert len(gateway_server.subscriptions) == 3


@pytest.mark.asyncio
async def test_a_limit_that_ends_soon_is_waited_for_and_the_request_then_succeeds(gateway_server, merchant_client, waiting):
    gateway_server.rate_limit = (1, 5)

    async with merchant_client as client:
        await client.create_subscription(**make_subscribe_args())
        created = await client.create_subscription(**make_subscribe_args())

    assert waiting == [5.0]
    assert created.subscription_id in gateway_server.subscriptions
    assert len(gateway_server.received_requests) == 3


@pytest.mark.asyncio
async def test_the_wait_is_what_remains_of_the_window(gateway_server, merchant_client, clock, waiting):
    gateway_server.rate_limit = (1, 10)

    async with merchant_client as client:
        await client.create_subscription(**make_subscribe_args())
        clock.advance(4)
        created = await client.create_subscription(**make_subscribe_args())

    assert waiting == [6.0]
    assert created.subscription_id in gateway_server.subscriptions


@pytest.mark.asyncio
async def test_the_limit_is_counted_per_api_key(gateway_server, merchant_client, clock, sleeps):
    gateway_server.rate_limit = (1, 60)
    other = gateway_server.add_platform()
    other_client = PolakoClient(test_env=True, company_id=other.company_id, api_key=other.api_key)

    async with merchant_client as client:
        await client.create_subscription(**make_subscribe_args())
    async with other_client as client:
        await client.create_subscription(**make_subscribe_args())

    assert len(gateway_server.subscriptions) == 2


@pytest.mark.asyncio
async def test_a_dropped_connection_is_retried_with_the_same_key(gateway_server, merchant_client, sleeps):
    gateway_server.drop_connection_next()
    key = make_idempotency_key()

    async with merchant_client as client:
        created = await client.create_subscription(**make_subscribe_args(), idempotency_key=key)

    assert len(gateway_server.received_requests) == 2
    assert {k for k, _ in keys_and_bodies(gateway_server)} == {key}
    assert created.subscription_id in gateway_server.subscriptions


@pytest.mark.asyncio
async def test_a_connection_that_keeps_dropping_is_a_client_error(gateway_server, merchant_client, sleeps):
    gateway_server.drop_connection_next(times=10)

    async with merchant_client as client:
        with pytest.raises(HttpClientError) as exc:
            await client.create_subscription(**make_subscribe_args())

    assert not isinstance(exc.value, HttpRequestError)
    assert len(gateway_server.received_requests) == 3


@pytest.mark.asyncio
async def test_a_server_that_is_not_listening_is_a_client_error(gateway_server, monkeypatch, sleeps):
    monkeypatch.setattr("polako.sdk._constants.BASE_URL_TEST", "http://127.0.0.1:1")
    platform = gateway_server.add_platform()
    client = PolakoClient(test_env=True, company_id=platform.company_id, api_key=platform.api_key)

    async with client:
        with pytest.raises(HttpClientError):
            await client.create_subscription(**make_subscribe_args())

    assert gateway_server.received_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setup, expected",
    [
        ("wrong_key", UnauthorizedError),
        ("other_company", ForbiddenError),
        ("disabled", ConflictError),
        ("bad_currency", RequestValidationError),
    ],
)
async def test_answers_that_are_final_are_not_retried(gateway_server, registered_platform, sleeps, setup, expected):
    api_key, company_id, args = registered_platform.api_key, registered_platform.company_id, make_subscribe_args()
    if setup == "wrong_key":
        api_key = generate_api_key()
    elif setup == "other_company":
        company_id = gateway_server.add_platform().company_id
    elif setup == "disabled":
        gateway_server.subscriptions_enabled = False
    else:
        args["currency"] = "EUR"
        gateway_server.allowed_currencies = ["RSD"]
    client = PolakoClient(test_env=True, company_id=company_id, api_key=api_key)

    async with client:
        with pytest.raises(expected):
            await client.create_subscription(**args)

    assert len(gateway_server.received_requests) == 1
    assert sleeps == []
