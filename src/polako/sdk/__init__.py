"""
Polako Finance Python SDK.

This SDK provides an async-only client for interacting with the Polako Finance
payment gateway API, following modern Python best practices.

Installation:
    pip install polako-finance

Example:
    from polako.sdk import PolakoClient, OrderDetails, OrderItem, CustomerInfo
    from decimal import Decimal
    from uuid import UUID

    async with PolakoClient() as client:
        order = OrderDetails(
            currency="RSD",
            language="en",
            order_id="ORDER-123",
            items=[OrderItem(name="Product", price=Decimal("100.00"), quantity=1, code=None, description=None, tax=None)],
            total=Decimal("100.00")
        )
        customer = CustomerInfo(email="customer@example.com", first_name=None, last_name=None, phone=None, address=None)
        session = await client.create_order(order, customer, UUID("your-platform-id"), "your-secret-key")
"""

from polako.sdk._async_api import AsyncPolakoClient as PolakoClient
from polako.sdk._exceptions import HttpClientError, HttpRequestError, PaymentInitError
from polako.sdk._order import CustomerAddress, CustomerInfo, OrderDetails, OrderItem, PaymentCallback, SessionInfo
from polako.sdk._payment import PaymentResult

__version__ = "0.1.1"

__all__ = [
    # Client
    "PolakoClient",
    # Models
    "CustomerAddress",
    "CustomerInfo",
    "OrderDetails",
    "OrderItem",
    "PaymentCallback",
    "PaymentResult",
    "SessionInfo",
    # Exceptions
    "HttpClientError",
    "HttpRequestError",
    "PaymentInitError",
]
