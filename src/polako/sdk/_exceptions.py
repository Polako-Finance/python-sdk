"""Exceptions for Polako Finance SDK."""

from typing import Optional


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


class PaymentInitError(HttpRequestError):
    """Exception raised when session creation succeeds but payment initiation fails.

    Carries the session_info so the caller can retry payment initiation
    or handle the orphaned session.

    Attributes:
        session_info: The successfully created SessionInfo from step 1
    """

    def __init__(
        self,
        message: str,
        session_info: "SessionInfo",
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ):
        """
        Initialize payment initiation error.

        Args:
            message: Error message describing the payment initiation failure
            session_info: SessionInfo from the successfully created session
            status_code: HTTP status code if available
            response_body: Response body if available
        """
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.session_info = session_info


# Avoid circular import — resolved at runtime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polako.sdk._order import SessionInfo
