"""A separate exception class per HTTP status, all still HttpRequestError."""

import pytest

from polako.sdk import (
    ConflictError,
    ForbiddenError,
    HttpClientError,
    HttpRequestError,
    NotFoundError,
    RateLimitedError,
    RequestValidationError,
    ServerError,
    UnauthorizedError,
)
from polako.sdk._async_client import AsyncHttpClient
from tests.generators import generate_api_key, generate_random_host, generate_readable_string

SPECIFIC = [
    (401, UnauthorizedError),
    (403, ForbiddenError),
    (404, NotFoundError),
    (409, ConflictError),
    (422, RequestValidationError),
    (429, RateLimitedError),
    (500, ServerError),
    (502, ServerError),
    (503, ServerError),
]


async def fetch(gateway, status, **response):
    gateway.respond(status=status, **response)
    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        await http.get("/v1/anything")


@pytest.mark.asyncio
@pytest.mark.parametrize("status, expected", SPECIFIC)
async def test_status_maps_to_its_own_class(gateway, status, expected):
    body = f'{{"detail": "{generate_readable_string(12)}"}}'

    with pytest.raises(expected) as exc:
        await fetch(gateway, status, text=body)

    assert type(exc.value) is expected
    assert exc.value.status_code == status
    assert exc.value.response_body == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status, expected", SPECIFIC)
async def test_specific_errors_stay_catchable_as_the_base_classes(gateway, status, expected):
    with pytest.raises(HttpRequestError):
        await fetch(gateway, status)
    with pytest.raises(HttpClientError):
        await fetch(gateway, status)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 410, 418])
async def test_other_statuses_stay_plain_http_request_error(gateway, status):
    with pytest.raises(HttpRequestError) as exc:
        await fetch(gateway, status)

    assert type(exc.value) is HttpRequestError


def test_specific_classes_are_distinct():
    classes = [expected for _, expected in SPECIFIC]
    for cls in set(classes):
        assert issubclass(cls, HttpRequestError)
    assert not issubclass(UnauthorizedError, ForbiddenError)
    assert not issubclass(ConflictError, RequestValidationError)
    assert not issubclass(NotFoundError, ForbiddenError)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header, expected",
    [("7", 7.0), ("0.5", 0.5), ("0", 0.0), (None, None), ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("soon", None), ("-3", None)],
)
async def test_rate_limited_error_carries_retry_after(gateway, header, expected):
    headers = {"Retry-After": header} if header is not None else None

    with pytest.raises(RateLimitedError) as exc:
        await fetch(gateway, 429, headers=headers)

    assert exc.value.retry_after == expected


@pytest.mark.asyncio
async def test_api_key_never_appears_in_the_exception(gateway):
    api_key = generate_api_key()
    gateway.respond(status=401, text='{"detail": "Client platform not found for the provided API key."}')

    async with AsyncHttpClient(f"https://{generate_random_host()}") as http:
        with pytest.raises(UnauthorizedError) as exc:
            await http.get("/v1/anything", headers={"company_api_key": api_key})

    error = exc.value
    for text in (str(error), repr(error), error.message, error.response_body or ""):
        assert api_key not in text
