"""Shared fixtures: an in-process fake gateway behind httpx.MockTransport."""

import json
from typing import Any, Callable, Dict, List, Optional, Union

import httpx
import pytest

from polako.sdk import PolakoClient

Handler = Callable[[httpx.Request], httpx.Response]
Step = Union[Dict[str, Any], Exception]


def build_response(status: int = 200, body: Optional[Dict[str, Any]] = None, text: Optional[str] = None, headers=None):
    content = text if text is not None else json.dumps(body if body is not None else {})
    return httpx.Response(status, content=content, headers=headers)


class FakeGateway:
    """Records every request and answers from a per-test handler."""

    def __init__(self) -> None:
        self.requests: List[httpx.Request] = []
        self._handler: Optional[Handler] = None

    def respond(
        self,
        status: int = 200,
        body: Optional[Dict[str, Any]] = None,
        text: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._handler = lambda request: build_response(status, body, text, headers)

    def sequence(self, *steps: Step) -> None:
        """Answer the n-th request with the n-th step; the last step repeats.

        A step is either a dict of `respond` arguments (status, body, text, headers) or an exception to raise.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            step = steps[min(len(self.requests) - 1, len(steps) - 1)]
            if isinstance(step, Exception):
                raise step
            return build_response(**step)

        self._handler = handler

    def fail(self, error: Exception) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise error

        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._handler is None:
            raise AssertionError("FakeGateway: no response configured for this test")
        return self._handler(request)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_json(self) -> Dict[str, Any]:
        return json.loads(self.last.content)


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    """Route every httpx.AsyncClient the SDK creates through a FakeGateway."""
    fake = FakeGateway()
    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(fake)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("polako.sdk._async_client.httpx.AsyncClient", factory)
    return fake


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """Replace the SDK's retry sleep with a recorder, so retry tests run instantly."""
    recorded: List[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr("polako.sdk._async_client._sleep", fake_sleep)
    return recorded


@pytest.fixture
def client() -> PolakoClient:
    return PolakoClient(test_env=True)
