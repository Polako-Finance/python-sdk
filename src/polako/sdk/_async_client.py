"""Async HTTP client for Polako Finance API."""

import asyncio
import json
from typing import Any, Dict, Literal, Optional, Type, TypeVar, Union

import httpx

from polako.sdk._exceptions import HttpClientError, HttpRequestError, RateLimitedError, error_class_for_status
from polako.sdk._serializable import Serializable

T = TypeVar("T", bound=Serializable)

IDEMPOTENCY_KEY_HEADER = "idempotency-key"

# Indirection so tests can replace the wait between retries.
_sleep = asyncio.sleep


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Seconds from a Retry-After header; None for a missing, negative or non-numeric value (e.g. an HTTP date)."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


# A repeat can cure these: the gateway was busy or restarting, or the network broke on the way.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


class AsyncHttpClient:
    """
    Async HTTP client wrapper for the payment gateway API.

    This client handles sending asynchronous requests to the gateway and parsing responses.
    Request and response bodies are serialized/deserialized using Serializable models.

    Retries: a request is retried only when it carries an ``Idempotency-Key`` header, because only then a repeat cannot
    do the work twice. Such a request is retried on HTTP 429, 500, 502, 503 and 504 and on network errors that a repeat can cure
    (timeouts, connection and protocol failures), with the same key and body, up to ``max_attempts`` attempts in total. A status
    such as 501 or 505, an unsupported address or too many redirects are not cured by a repeat and are raised at once. Every
    other request is sent exactly once.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
        max_attempts: int = 3,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 8.0,
    ):
        """
        Initialize the async HTTP client.

        Args:
            base_url: Base URL of the payment gateway API
            timeout: Request timeout in seconds (default: 30.0)
            headers: Optional additional headers to include in all requests
            max_attempts: Total attempts for a request that carries an Idempotency-Key (default: 3)
            retry_base_delay: Delay before the first retry in seconds; doubles on every further retry (default: 0.5)
            retry_max_delay: Upper bound for one wait, also the longest Retry-After that is waited for (default: 8.0)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._default_headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if headers:
            self._default_headers.update(headers)

        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AsyncHttpClient":
        """Enter async context manager."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _build_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Build request headers by merging default headers with extra headers."""
        headers = self._default_headers.copy()
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _serialize_body(self, body: Optional[Union[Serializable, Dict[str, Any]]]) -> Optional[str]:
        """
        Serialize request body to JSON string.

        Args:
            body: Serializable instance or dictionary to serialize

        Returns:
            JSON string or None if body is None
        """
        if body is None:
            return None

        if isinstance(body, Serializable):
            return body.to_json()
        elif isinstance(body, dict):
            return json.dumps(body)
        else:
            raise ValueError(f"Body must be Serializable instance or dict, got {type(body)}")

    def _deserialize_response(self, response_text: str, response_model: Type[T]) -> T:
        """
        Deserialize response body from JSON string to Serializable instance.

        Args:
            response_text: JSON string response
            response_model: Serializable class to deserialize into

        Returns:
            Instance of response_model
        """
        try:
            return response_model.from_json(response_text)
        except json.JSONDecodeError as e:
            raise HttpRequestError(f"Failed to parse JSON response: {e}", response_body=response_text) from e
        except Exception as e:
            raise HttpRequestError(
                f"Failed to deserialize response to {response_model.__name__}: {e}",
                response_body=response_text,
            ) from e

    def _handle_response(
        self,
        response: httpx.Response,
        response_model: Optional[Type[T]] = None,
    ) -> Optional[T]:
        """
        Handle HTTP response, raising errors for non-2xx status codes.

        Args:
            response: httpx Response object
            response_model: Optional Serializable class to deserialize response into

        Returns:
            Deserialized response model instance or None if response_model is not provided

        Raises:
            HttpRequestError: If response status code is not 2xx
        """
        response_text = response.text

        if not response.is_success:
            message = f"HTTP request failed with status {response.status_code}: {response_text}"
            error_class = error_class_for_status(response.status_code)
            if error_class is RateLimitedError:
                raise RateLimitedError(
                    message,
                    status_code=response.status_code,
                    response_body=response_text,
                    retry_after=_parse_retry_after(response.headers.get("Retry-After")),
                )
            raise error_class(message, status_code=response.status_code, response_body=response_text)

        if response_model is None:
            return None

        if not response_text.strip():
            raise HttpRequestError("Response body is empty", status_code=response.status_code)

        return self._deserialize_response(response_text, response_model)

    async def request(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an async HTTP request to the gateway.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            path: API endpoint path (relative to base_url)
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers for this request
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None if response_model is not provided

        Raises:
            HttpRequestError: If the request fails or response cannot be parsed
            httpx.RequestError: If there's a network error
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = self._build_headers(headers)
        json_body = self._serialize_body(request_body)
        max_attempts = self.max_attempts if self._has_idempotency_key(request_headers) else 1

        try:
            for attempt in range(1, max_attempts + 1):
                is_last = attempt == max_attempts
                try:
                    response = await self._send(method, url, json_body, request_headers, params)
                except httpx.RequestError as e:
                    if is_last or not isinstance(e, RETRYABLE_ERRORS):
                        raise HttpClientError(f"Network error during request: {e}") from e
                    await _sleep(self._backoff(attempt))
                    continue

                if not is_last and self._is_retryable(response.status_code):
                    delay = self._retry_delay(attempt, response)
                    if delay is not None:
                        await _sleep(delay)
                        continue

                return self._handle_response(response, response_model)

            raise AssertionError("unreachable: the last attempt always returns or raises")
        except HttpClientError:
            raise
        except Exception as e:
            raise HttpRequestError(f"Unexpected error during request: {e}") from e

    async def _send(
        self,
        method: str,
        url: str,
        content: Optional[str],
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
    ) -> httpx.Response:
        """Send one HTTP request with the shared client, or with a one-off client outside the context manager."""
        if self._client:
            return await self._client.request(method=method, url=url, content=content, headers=headers, params=params)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.request(method=method, url=url, content=content, headers=headers, params=params)

    @staticmethod
    def _has_idempotency_key(headers: Dict[str, str]) -> bool:
        return any(name.lower() == IDEMPOTENCY_KEY_HEADER for name in headers)

    @staticmethod
    def _is_retryable(status_code: int) -> bool:
        return status_code in RETRYABLE_STATUSES

    def _backoff(self, attempt: int) -> float:
        """Exponential wait before retry number `attempt`, capped."""
        return min(self.retry_base_delay * float(2 ** (attempt - 1)), self.retry_max_delay)

    def _retry_delay(self, attempt: int, response: httpx.Response) -> Optional[float]:
        """Seconds to wait before the next attempt, or None when waiting is not worth it (give up and raise)."""
        delay = self._backoff(attempt)
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is None:
            return delay
        if retry_after > self.retry_max_delay:
            return None
        return max(delay, retry_after)

    async def get(
        self,
        path: str,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an async GET request.

        Args:
            path: API endpoint path
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return await self.request("GET", path, response_model=response_model, headers=headers, params=params)

    async def post(
        self,
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an async POST request.

        Args:
            path: API endpoint path
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return await self.request(
            "POST",
            path,
            request_body=request_body,
            response_model=response_model,
            headers=headers,
            params=params,
        )

    async def put(
        self,
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an async PUT request.

        Args:
            path: API endpoint path
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return await self.request(
            "PUT",
            path,
            request_body=request_body,
            response_model=response_model,
            headers=headers,
            params=params,
        )

    async def patch(
        self,
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an async PATCH request.

        Args:
            path: API endpoint path
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return await self.request(
            "PATCH",
            path,
            request_body=request_body,
            response_model=response_model,
            headers=headers,
            params=params,
        )

    async def delete(
        self,
        path: str,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an async DELETE request.

        Args:
            path: API endpoint path
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return await self.request("DELETE", path, response_model=response_model, headers=headers, params=params)
