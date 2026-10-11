"""Fixtures for the end-to-end tests: a gateway emulator on a free port and a client pointed at it."""

import pytest
import pytest_asyncio

from polako.sdk import PolakoClient
from tests.integration.gateway_test_server import GatewayTestServer, Platform
from tests.integration.merchant_receiver import MerchantReceiver


@pytest_asyncio.fixture
async def gateway_server(monkeypatch):
    """The emulator, running; the SDK's test-environment URL points at it for the length of the test."""
    server = GatewayTestServer()
    async with server.run():
        monkeypatch.setattr("polako.sdk._constants.BASE_URL_TEST", server.base_url)
        yield server


@pytest.fixture
def registered_platform(gateway_server) -> Platform:
    """A platform known to the emulator, like one a merchant created in the dashboard."""
    return gateway_server.add_platform()


@pytest_asyncio.fixture
async def merchant_receiver(gateway_server, registered_platform):
    """The merchant's webhook endpoint, running, and registered as the platform's callback URL."""
    receiver = MerchantReceiver(api_key=registered_platform.api_key)
    async with receiver.run():
        registered_platform.callback_url = receiver.webhook_url
        yield receiver


@pytest.fixture
def merchant_client(registered_platform) -> PolakoClient:
    """A client configured the way that merchant configures it."""
    return PolakoClient(test_env=True, company_id=registered_platform.company_id, api_key=registered_platform.api_key)
