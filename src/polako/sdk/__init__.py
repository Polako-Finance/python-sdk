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
from polako.sdk._constants import BillingInterval
from polako.sdk._exceptions import (
    ConfigurationError,
    ConflictError,
    ForbiddenError,
    HttpClientError,
    HttpRequestError,
    MissingSignatureError,
    RateLimitedError,
    RequestValidationError,
    ServerError,
    UnauthorizedError,
    WebhookPayloadError,
    WebhookSignatureError,
)
from polako.sdk._order import (
    CartItem,
    CustomerAddress,
    CustomerInfo,
    InitCustomerInfo,
    MerchantInfo,
    OrderDetails,
    OrderItem,
    OrderStatusItem,
    OrderStatusResponse,
    PaymentCallback,
    PaymentConfig,
    PaymentOption,
    PaymentSessionDetails,
    PaymentUrlResult,
    RefundedItem,
    RefundItem,
    RefundResponse,
    SessionCustomerInfo,
    SessionInfo,
    ShoppingCart,
)
from polako.sdk._subscription import (
    FormPost,
    HppFormPost,
    RedirectForm,
    SubscriptionCreated,
    UnknownRegistrationFormError,
)
from polako.sdk._webhook import (
    ChargeFailed,
    ChargeSucceeded,
    DroppedExternally,
    SubscriptionCancelled,
    SubscriptionWebhookEvent,
    UnknownSubscriptionEvent,
    parse_subscription_webhook,
)

__version__ = "0.1.9"

__all__ = [
    # Client
    "PolakoClient",
    # Models
    "CartItem",
    "CustomerAddress",
    "CustomerInfo",
    "InitCustomerInfo",
    "MerchantInfo",
    "OrderDetails",
    "OrderItem",
    "OrderStatusItem",
    "OrderStatusResponse",
    "PaymentCallback",
    "PaymentConfig",
    "PaymentOption",
    "PaymentSessionDetails",
    "PaymentUrlResult",
    "RefundedItem",
    "RefundItem",
    "RefundResponse",
    "SessionCustomerInfo",
    "SessionInfo",
    "ShoppingCart",
    # Subscriptions
    "BillingInterval",
    "FormPost",
    "HppFormPost",
    "RedirectForm",
    "SubscriptionCreated",
    "ChargeSucceeded",
    "ChargeFailed",
    "DroppedExternally",
    "SubscriptionCancelled",
    "UnknownSubscriptionEvent",
    "SubscriptionWebhookEvent",
    "parse_subscription_webhook",
    # Exceptions
    "ConfigurationError",
    "WebhookSignatureError",
    "MissingSignatureError",
    "WebhookPayloadError",
    "UnknownRegistrationFormError",
    "HttpClientError",
    "HttpRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "ConflictError",
    "RequestValidationError",
    "RateLimitedError",
    "ServerError",
]
