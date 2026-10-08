"""Exceptions for Polako Finance SDK."""

from typing import Dict, Optional, Type


class ConfigurationError(ValueError):
    """The client is not configured for the requested call (e.g. no company ID or API key for a subscription)."""


class WebhookSignatureError(Exception):
    """The signature of a webhook does not match its body: the request was not sent by the gateway, or was altered."""


class MissingSignatureError(WebhookSignatureError):
    """A webhook came without a signature although one is required."""


class WebhookPayloadError(ValueError):
    """The body of a webhook is not a valid event: it is not JSON, a field is missing or a value is malformed."""


class HttpClientError(Exception):
    """Base exception for HTTP client errors."""

    def __init__(self, message: str):
        """
        Initialize HTTP client error.

        Args:
            message: Error message
        """
        super().__init__(message)
        self.message = message


class HttpRequestError(HttpClientError):
    """Exception raised when an HTTP request fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        """
        Initialize HTTP request error.

        Args:
            message: Error message
            status_code: HTTP status code if available
            response_body: Response body if available
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class UnauthorizedError(HttpRequestError):
    """HTTP 401: the API key or token is missing or unknown."""


class ForbiddenError(HttpRequestError):
    """HTTP 403: the credentials are valid but do not allow this operation (e.g. a key of another company)."""


class ConflictError(HttpRequestError):
    """HTTP 409: the request conflicts with the current state (e.g. a duplicate subscription, a feature that is off)."""


class RequestValidationError(HttpRequestError):
    """HTTP 422: the server rejected the request fields."""


class RateLimitedError(HttpRequestError):
    """HTTP 429: too many requests. `retry_after` is the number of seconds the server asked to wait, if it said."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        retry_after: Optional[float] = None,
    ):
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.retry_after = retry_after


class ServerError(HttpRequestError):
    """HTTP 5xx: the gateway or an upstream provider failed."""


_ERRORS_BY_STATUS: Dict[int, Type[HttpRequestError]] = {
    401: UnauthorizedError,
    403: ForbiddenError,
    409: ConflictError,
    422: RequestValidationError,
    429: RateLimitedError,
}


def error_class_for_status(status_code: int) -> Type[HttpRequestError]:
    """Return the exception class for a non-2xx status; statuses without a dedicated class give HttpRequestError."""
    if status_code >= 500:
        return ServerError
    return _ERRORS_BY_STATUS.get(status_code, HttpRequestError)
