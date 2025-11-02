import json
from typing import Any, Dict, Literal, Optional, Type, TypeVar, Union

import httpx

from polako._serializable import Serializable

T = TypeVar("T", bound=Serializable)


class HttpClientError(Exception):
    """Base exception for HTTP client errors."""

    pass


class HttpRequestError(HttpClientError):
    """Exception raised when an HTTP request fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class HttpClient:
    """
    HTTP client wrapper for the payment gateway API.

    This client handles sending requests to the gateway and parsing responses.
    Request and response bodies are serialized/deserialized using Serializable models.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the HTTP client.

        Args:
            base_url: Base URL of the payment gateway API
            timeout: Request timeout in seconds (default: 30.0)
            headers: Optional additional headers to include in all requests
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._default_headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if headers:
            self._default_headers.update(headers)

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
            raise HttpRequestError(f"Failed to parse JSON response: {e}", response_body=response_text)
        except Exception as e:
            raise HttpRequestError(
                f"Failed to deserialize response to {response_model.__name__}: {e}",
                response_body=response_text,
            )

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
            raise HttpRequestError(
                f"HTTP request failed with status {response.status_code}: {response_text}",
                status_code=response.status_code,
                response_body=response_text,
            )

        if response_model is None:
            return None

        if not response_text.strip():
            raise HttpRequestError("Response body is empty", status_code=response.status_code)

        return self._deserialize_response(response_text, response_model)

    def request(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send an HTTP request to the gateway.

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

        try:
            response = httpx.request(
                method=method,
                url=url,
                content=json_body,
                headers=request_headers,
                params=params,
                timeout=self.timeout,
            )

            return self._handle_response(response, response_model)

        except httpx.RequestError as e:
            raise HttpClientError(f"Network error during request: {e}") from e
        except HttpRequestError:
            raise
        except Exception as e:
            raise HttpRequestError(f"Unexpected error during request: {e}") from e

    def get(
        self,
        path: str,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send a GET request.

        Args:
            path: API endpoint path
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return self.request("GET", path, response_model=response_model, headers=headers, params=params)

    def post(
        self,
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send a POST request.

        Args:
            path: API endpoint path
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return self.request(
            "POST",
            path,
            request_body=request_body,
            response_model=response_model,
            headers=headers,
            params=params,
        )

    def put(
        self,
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send a PUT request.

        Args:
            path: API endpoint path
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return self.request(
            "PUT",
            path,
            request_body=request_body,
            response_model=response_model,
            headers=headers,
            params=params,
        )

    def patch(
        self,
        path: str,
        request_body: Optional[Union[Serializable, Dict[str, Any]]] = None,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send a PATCH request.

        Args:
            path: API endpoint path
            request_body: Optional Serializable instance or dict for request body
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return self.request(
            "PATCH",
            path,
            request_body=request_body,
            response_model=response_model,
            headers=headers,
            params=params,
        )

    def delete(
        self,
        path: str,
        response_model: Optional[Type[T]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Send a DELETE request.

        Args:
            path: API endpoint path
            response_model: Optional Serializable class to deserialize response into
            headers: Optional additional headers
            params: Optional query parameters

        Returns:
            Deserialized response model instance or None
        """
        return self.request("DELETE", path, response_model=response_model, headers=headers, params=params)
