"""Async HTTP client for Polako Finance API."""

import asyncio
import json
import logging
import re
import ssl
import sys
import warnings
from typing import Any, Dict, Iterator, Literal, Optional, Set, Type, TypeVar, Union

import anyio
import httpx

from polako.sdk._exceptions import (
    HttpClientError,
    HttpRequestError,
    InvalidArgumentError,
    InvalidHeaderValueError,
    RateLimitedError,
    error_class_for_status,
)
from polako.sdk._serializable import Serializable

T = TypeVar("T", bound=Serializable)

logger = logging.getLogger(__name__)

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


def _with_detail(prefix: str, detail: str) -> str:
    """``prefix: detail``, or just ``prefix`` when the detail is blank, so a message never ends after a colon."""
    detail = detail.strip()
    return f"{prefix}: {detail}" if detail else prefix


def _error_chain(error: BaseException) -> Iterator[BaseException]:
    """The error and what it was raised because of: its ``__cause__``, or its ``__context__`` when ``raise ... from
    None`` suppressed it (httpcore re-raises a cut handshake or a reset connection that way, so the readable reason
    survives only there). A context that was not suppressed is whatever the caller happened to be handling, which
    has nothing to do with this failure, so it is not followed; neither is anything past an error of the SDK."""
    seen = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        if isinstance(current, HttpClientError):
            return
        current = current.__cause__ or (current.__context__ if current.__suppress_context__ else None)


def _os_error_text(error: BaseException) -> str:
    """The class and text of the innermost ``OSError`` with a text on the chain of the error."""
    found = ""
    for link in _error_chain(error):
        if isinstance(link, OSError) and str(link).strip():
            found = _with_detail(type(link).__name__, str(link))
    return found


def _describe_network_error(error: BaseException) -> str:
    """The failure's class and text. httpx raises the timeouts and a reset connection with an empty text, so the
    class name is what says what happened. For an error of httpx without a text, the reason found deeper on the
    error chain is used; any other error is described by itself, so that the text of an unrelated error found on
    its chain is never taken for its reason. The original error stays available as ``__cause__``."""
    name = type(error).__name__
    text = str(error).strip()
    if not text and isinstance(error, httpx.RequestError):
        text = _os_error_text(error)
    return _with_detail(name, text)


def is_sendable_header_value(value: Union[str, bytes]) -> bool:
    """Printable ASCII (a tab inside is allowed) without whitespace at either end: anything else is refused by the
    HTTP layer. ``bytes`` is judged by its ASCII text; any other type cannot be sent."""
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(value, str):
        return False
    return value.isascii() and all(c.isprintable() or c == "\t" for c in value) and value == value.strip()


# The characters of a header name (RFC 9110 token).
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


def _is_sendable_header_name(name: Union[str, bytes]) -> bool:
    """A non-empty token of ASCII letters, digits and ``!#$%&'*+-.^_`|~``, as text or as bytes."""
    if isinstance(name, bytes):
        try:
            name = name.decode("ascii")
        except UnicodeDecodeError:
            return False
    return isinstance(name, str) and _HEADER_NAME.fullmatch(name) is not None


def _check_header_values(headers: Dict[str, str]) -> None:
    """Refuse a header that cannot be sent before anything is sent. A value is named by its header only: it may be a
    secret and must not appear in an error message, a traceback or ``__cause__``."""
    for name, value in headers.items():
        if not _is_sendable_header_name(name):
            raise InvalidArgumentError(f"The header name {name!r} cannot be sent: it must be a non-empty ASCII token")
        if not is_sendable_header_value(value):
            raise InvalidHeaderValueError(
                f"The value of the {name!r} header cannot be sent: it must be text (or bytes) of printable ASCII without "
                "leading or trailing whitespace (a value read from a file often ends with a newline)"
            )


def _after_attempts(attempt: int) -> str:
    """Tail of a message that tells how many attempts were made; empty after the first one."""
    return f" (after {attempt} attempts; the message is about the last one)" if attempt > 1 else ""


# A repeat can cure these: the gateway was busy or restarting, or the network broke on the way.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
# What the transport may raise without httpx wrapping it, when a repeat can cure it: a connection that was reset,
# aborted, refused or broken, a timeout of the system.
_TRANSIENT_OS_ERRORS = (ConnectionError, TimeoutError)
# What anyio raises for a stream that was cut, when the httpcore in use does not map it to an error of its own. Some
# httpcore versions may let these through (an older one did not map the end of a stream during the handshake; this was
# not checked against the sources of each version, and the catch does not depend on it).
_CUT_STREAM_ERRORS = (anyio.EndOfStream, anyio.BrokenResourceError)
# TLS failures that a repeat cures. The ``reason`` code is matched, not the text of the message, and only what is
# named is retried, so that a code the running Python does not know (its table of reasons is the one it was built
# with, and an unknown code has ``reason`` None) is never retried by mistake.
#
# 1. A connection that was cut: the class says it. This is what can be retried while connecting (``httpx.ConnectError``,
#    where the handshake happens). Any other TLS failure of the handshake (a certificate, a protocol version, a cipher,
#    a key that is too small, a peer or a proxy that answers in plain text) is a deterministic fault of the setup, and
#    a repeat gives the same result.
_CUT_CONNECTION_ERRORS = (ssl.SSLEOFError, ssl.SSLZeroReturnError, ssl.SSLSyscallError)
# Defensive: CPython raises this reason as SSLEOFError, but a plain SSLError that carries it is the same event.
_CUT_CONNECTION_REASONS = frozenset({"UNEXPECTED_EOF_WHILE_READING"})


def _is_cut_connection(error: ssl.SSLError) -> bool:
    return isinstance(error, _CUT_CONNECTION_ERRORS) or getattr(error, "reason", None) in _CUT_CONNECTION_REASONS


# 2. On an established connection a TLS error reaches the SDK as it is, unwrapped (anyio re-raises it and httpcore
#    has no mapping for it). There a damaged record is also cured by a repeat. The alerts that a server sends for a
#    message it cannot decode or did not expect (SSLV3_ALERT_UNEXPECTED_MESSAGE, TLSV1_ALERT_DECODE_ERROR) are not on
#    the list: under TLS 1.3 the handshake is finished for the client before the server judges its last flight, so such
#    a rejection also arrives unwrapped, on the first read, and a repeat gives the same result.
_DAMAGED_RECORD_REASONS = frozenset(
    {
        "DECRYPTION_FAILED_OR_BAD_RECORD_MAC",
        "DECRYPTION_FAILED",
        "BAD_RECORD_MAC",
        "SSLV3_ALERT_BAD_RECORD_MAC",
        "RECORD_LAYER_FAILURE",
        "UNEXPECTED_RECORD",
        "BAD_LENGTH",
        "PACKET_LENGTH_TOO_LONG",
        "APPLICATION_DATA_AFTER_CLOSE_NOTIFY",
    }
)


def _is_retryable_error(error: BaseException) -> bool:
    """Whether a repeat can cure the failure. A repeat of a failure that is permanent gives the same result and spends
    the rate limit, so it is not retried.

    A failure to connect (``httpx.ConnectError``) with a TLS error on its chain is retried only if the connection was
    cut. A TLS error that nothing wrapped comes from an established connection and is retried if the connection was
    cut or a record was damaged. Every other error is retried by its kind; this includes ``ReadError`` and
    ``WriteError``, which httpx raises for a stream that broke, and the end of a stream, which arrives as
    ``RemoteProtocolError``. A stream that anyio reports as cut (``EndOfStream``, ``BrokenResourceError``) and
    that an older httpcore does not map is retried like one that httpx reports."""
    if isinstance(error, httpx.ConnectError):
        tls_error = next((link for link in _error_chain(error) if isinstance(link, ssl.SSLError)), None)
        if tls_error is not None:
            return _is_cut_connection(tls_error)
    elif isinstance(error, ssl.SSLError):
        return _is_cut_connection(error) or getattr(error, "reason", None) in _DAMAGED_RECORD_REASONS
    if isinstance(error, RETRYABLE_ERRORS):
        return True
    return isinstance(error, _TRANSIENT_OS_ERRORS + _CUT_STREAM_ERRORS)


CLOSE_TIMEOUT = 10.0  # seconds the close of a client may take before it is given up


def _is_sdk_module(name: str) -> bool:
    return name == "polako.sdk" or name.startswith("polako.sdk.")


def _stacklevel_outside_sdk() -> int:
    """The ``stacklevel`` for ``warnings.warn``, called from the function that calls this one, that points at the first
    frame outside the SDK: the code of the merchant that made the mistake, not the SDK's own ``__aexit__``."""
    level, frame = 1, sys._getframe(1)
    while frame is not None and _is_sdk_module(frame.f_globals.get("__name__", "")):
        frame, level = frame.f_back, level + 1
    return level


def _log_failed_close(finished: "asyncio.Future") -> None:
    """Log the failure of ``aclose``, whenever it comes: also one that comes after the SDK gave up waiting."""
    if not finished.cancelled() and finished.exception() is not None:
        error = finished.exception()
        logger.warning("Closing the HTTP client failed: %s", _describe_network_error(error), exc_info=error)


def _log_cancelled_close(finished: "asyncio.Future") -> None:
    """Log a close task that was cancelled, also one that was cancelled before it ran a single step."""
    if finished.cancelled():
        logger.warning("Closing the HTTP client was cancelled before it ended; its connections may stay open")


async def _close_with_timeout(client: httpx.AsyncClient, keep: Set["asyncio.Future"]) -> None:
    """Close the client, bounded in time. No failure of the close goes further than the log: it must not replace the
    outcome of the call that closes the client (a subscription that was created) or an error that is propagating.

    The deadline is the SDK's own: ``aclose`` runs as a task that is waited for with a timeout, so that a
    ``TimeoutError`` that ``aclose`` raises by itself is a failure like any other and is never taken for the deadline.
    The task is kept in ``keep`` until it is done, also after the SDK gave up waiting, because asyncio keeps only weak
    references to tasks and an ``aclose`` that survives a cancellation could be collected in the middle.

    A close that is cancelled, when the event loop shuts down, is logged by the caller of this function (see ``_close``);
    the connections may stay open, and with a loop that is closed without cancelling its tasks asyncio itself reports
    ``Task was destroyed but it is pending``."""
    closing = asyncio.ensure_future(client.aclose())
    keep.add(closing)
    closing.add_done_callback(keep.discard)
    closing.add_done_callback(_log_failed_close)
    try:
        done, _ = await asyncio.wait({closing}, timeout=CLOSE_TIMEOUT)
    except asyncio.CancelledError:
        closing.cancel()
        raise
    if not done:
        closing.cancel()
        logger.warning(
            "Closing the HTTP client timed out after %s seconds; its connections may stay open until they are collected",
            CLOSE_TIMEOUT,
        )


class AsyncHttpClient:
    """
    Async HTTP client wrapper for the payment gateway API.

    This client handles sending asynchronous requests to the gateway and parsing responses.
    Request and response bodies are serialized/deserialized using Serializable models.

    Retries: a request is retried only when it carries an ``Idempotency-Key`` header, because only then a repeat cannot
    do the work twice. Such a request is retried on HTTP 429, 500, 502, 503 and 504 and on network errors that a repeat can cure
    (timeouts, connection and protocol failures, and the transient errors of the transport that httpx does not wrap: a
    connection that was reset, aborted, refused or broken, a timeout of the system, a cut TLS connection), with the same key
    and body, up to ``max_attempts`` attempts in total. A status such as 501 or 505, an unsupported address, too many
    redirects, a certificate that does not verify, a wrong TLS protocol version and a failure to set up the client (an
    unreadable certificate file, a proxy setting that cannot be used) are not cured by a repeat and are raised at once. A TLS
    failure while connecting is retried only if the connection was cut; on an established connection also a damaged record
    is retried (told apart by the ``reason`` code of the error, not by its text). Every other request is sent exactly once.
    A failure is an ``HttpClientError`` whose message names the failure and, after a retry, the number of attempts.
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
        self._entered = 0  # how many `async with` blocks are open on this object
        self._in_flight = 0  # how many calls use the shared client at this moment
        self._closing: Set[asyncio.Future] = set()  # the tasks that close clients, kept until they are done

    def _new_client(self) -> httpx.AsyncClient:
        """The httpx client. Building it reads the certificate file and the proxy settings of the environment, so it
        fails when ``SSL_CERT_FILE`` names a file that exists but is unreadable or malformed, or when a proxy setting
        cannot be used (an unknown scheme, a bad URL or port, a SOCKS proxy without the ``socksio`` package). What fails
        depends on the version of httpx: before 0.28 a missing ``SSL_CERT_FILE`` is skipped, from 0.28 it fails here.

        A failure of the environment (``OSError``, ``ValueError``, ``ImportError``, ``httpx.InvalidURL``) is an
        ``HttpClientError`` with the error as the cause, and a repeat cannot cure it. Any other error is a mistake in
        the code or a change in httpx, and is raised as it is, not hidden as a failure of the network."""
        try:
            return httpx.AsyncClient(timeout=self.timeout)
        except (OSError, ValueError, ImportError, httpx.InvalidURL) as e:
            raise HttpClientError(_with_detail("Client set-up failed", _describe_network_error(e))) from e

    async def __aenter__(self) -> "AsyncHttpClient":
        """Enter async context manager.

        Raises:
            HttpClientError: If the client cannot be set up, e.g. ``SSL_CERT_FILE`` names a file that is malformed
                (from httpx 0.28 also one that is missing), or a proxy setting cannot be used. This happens
                here, not at a call, so keep ``async with`` inside the ``try`` of your error handling.

        Entering again (nested, or from another task) shares the client that is open. It is closed when the last
        context has exited and no call is still using it.
        """
        if self._client is None:
            self._client = self._new_client()
        self._entered += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager.

        An exit without a matching entry (a shutdown hook that runs twice, a client that was never entered) does
        nothing but warn: ``RuntimeWarning`` now, and it will be a ``RuntimeError`` from 0.3.0. If the merchant's
        filters turn warnings into errors the warning raises, so that a test suite catches it, unless an error is
        propagating or being handled: then the warning is logged instead, because it would replace that error.

        A failure of closing the client does not raise: it is logged (see ``_close``).
        """
        if self._entered == 0:
            message = "The client was exited more often than it was entered; this will be a RuntimeError from 0.3.0"
            handling_an_error = exc_type is not None or sys.exc_info()[0] is not None  # before the handler below
            try:
                warnings.warn(message, RuntimeWarning, stacklevel=_stacklevel_outside_sdk())
            except RuntimeWarning:  # the merchant's filters turn warnings into errors
                if not handling_an_error:
                    raise  # nothing to replace: let the merchant's test suite see it
                logger.warning(message)  # an error is propagating or being handled: do not replace it
            return
        self._entered -= 1
        await self._close_if_unused()

    async def _close_if_unused(self) -> None:
        """Close the shared client once no ``async with`` is open and no call is using it."""
        if self._entered == 0 and self._in_flight == 0 and self._client is not None:
            client, self._client = self._client, None
            await self._close(client)

    async def _close(self, client: httpx.AsyncClient) -> None:
        """Close the client in a task that the SDK keeps until it is done, bounded by ``CLOSE_TIMEOUT``, and wait for it.
        No failure of the close comes out of here (see ``_close_with_timeout``).

        If the caller is cancelled while it waits, it leaves at once, with its cancellation, and the close goes on in the
        background to its end or its timeout. ``asyncio.wait`` is used, not ``shield``, because it tells the two
        cancellations apart on every Python: a cancelled caller gets ``CancelledError``, a cancelled close task only
        ends the wait (and is logged, see ``_log_cancelled_close``), so a caller that is not cancelled goes on."""
        task = asyncio.ensure_future(_close_with_timeout(client, self._closing))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)
        task.add_done_callback(_log_cancelled_close)
        await asyncio.wait({task})

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
            raise InvalidArgumentError(f"Body must be Serializable instance or dict, got {type(body)}")

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
        attempt: int = 1,
    ) -> Optional[T]:
        """
        Handle HTTP response, raising errors for non-2xx status codes.

        Args:
            response: httpx Response object
            response_model: Optional Serializable class to deserialize response into
            attempt: Number of the attempt that got this response; a message after a retry says so

        Returns:
            Deserialized response model instance or None if response_model is not provided

        Raises:
            HttpRequestError: If response status code is not 2xx
        """
        response_text = response.text

        if not response.is_success:
            message = _with_detail(f"HTTP request failed with status {response.status_code}", response_text)
            message += _after_attempts(attempt)
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
            InvalidArgumentError: If a header name is not an ASCII token
            InvalidHeaderValueError: If a header value is not printable ASCII or has whitespace at either end
            HttpRequestError: If the gateway answers with an error status or the answer cannot be parsed
            HttpClientError: If the request fails before an answer arrives, e.g. a refused connection or a timeout
                (the original error is its ``__cause__``), or the client cannot be set up (a malformed SSL_CERT_FILE,
                a proxy setting that cannot be used)
        """
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_headers = self._build_headers(headers)
        _check_header_values(request_headers)
        json_body = self._serialize_body(request_body)
        max_attempts = self.max_attempts if self._has_idempotency_key(request_headers) else 1

        # Outside `async with` one client serves all attempts and is closed at the end; it is built before the loop,
        # so that a failure to set it up is not mistaken for a failure of an attempt and retried.
        owned = self._client is None
        client = self._new_client() if owned else self._client
        if not owned:
            self._in_flight += 1  # the last `async with` that exits meanwhile must not close the client under this call
        try:
            return await self._attempts(client, method, url, json_body, request_headers, params, response_model, max_attempts)
        finally:
            if owned:
                await self._close(client)
            else:
                self._in_flight -= 1
                await self._close_if_unused()

    async def _attempts(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        json_body: Optional[str],
        request_headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
        response_model: Optional[Type[T]],
        max_attempts: int,
    ) -> Optional[T]:
        """Send the request, up to ``max_attempts`` times, and turn the outcome into a result or an error."""
        try:
            for attempt in range(1, max_attempts + 1):
                is_last = attempt == max_attempts
                try:
                    response = await self._send(client, method, url, json_body, request_headers, params)
                except (httpx.RequestError, OSError, *_CUT_STREAM_ERRORS) as e:
                    if is_last or not _is_retryable_error(e):
                        raise HttpClientError(f"Request failed: {_describe_network_error(e)}{_after_attempts(attempt)}") from e
                    await _sleep(self._backoff(attempt))
                    continue

                if not is_last and self._is_retryable(response.status_code):
                    delay = self._retry_delay(attempt, response)
                    if delay is not None:
                        await _sleep(delay)
                        continue

                return self._handle_response(response, response_model, attempt)

            raise AssertionError("unreachable: the last attempt always returns or raises")
        except HttpClientError:
            raise
        except Exception as e:
            raise HttpRequestError(_with_detail("Unexpected error during request", _describe_network_error(e))) from e

    @staticmethod
    async def _send(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        content: Optional[str],
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
    ) -> httpx.Response:
        """Send one HTTP request."""
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
