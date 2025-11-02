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
