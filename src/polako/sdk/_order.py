"""Data models for orders, customers, and payment callbacks."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from polako.sdk._constants import CURRENCIES, LANGUAGES, TAX_SCHEMAS, TCurrency, TLanguage, TTaxSchema
from polako.sdk._serializable import Serializable


@dataclass
class OrderItem(Serializable):
    """
    Represents a single item in an order.

    Attributes:
        code: Optional item code/SKU
        name: Item name (required)
        description: Optional item description
        price: Item price (must be positive)
        quantity: Item quantity (must be positive integer)
        tax: Optional tax schema (VAT, No_VAT, or Reduced_VAT)
    """

    code: Optional[str]
    name: str
    description: Optional[str]
    price: Decimal
    quantity: int
    tax: Optional[TTaxSchema]

    def validate(self) -> None:
        """
        Validate order item fields.

        Raises:
            ValueError: If any field validation fails
        """
        if not self.name:
            raise ValueError("'name' is required")

        if self.price <= 0:
            raise ValueError("'price' must be positive")

        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("'quantity' must be a positive integer")

        if self.tax is not None and self.tax not in TAX_SCHEMAS:
            raise ValueError(f"invalid 'tax' value '{self.tax}', must be one of {TAX_SCHEMAS}")


@dataclass
class OrderDetails(Serializable):
    """
    Represents order details for payment processing.

    Attributes:
        currency: Optional currency code (defaults to RSD if not specified)
        language: Optional language code (sr, en, or ru)
        order_id: Optional order identifier
        items: List of order items (must not be empty)
        total: Total order amount (must be positive)
    """

    currency: Optional[TCurrency]
    language: Optional[TLanguage]
    order_id: Optional[str]
    items: List[OrderItem]
    total: Decimal

    def validate(self) -> None:
        """
        Validate order details and all items.

        Raises:
            ValueError: If any field validation fails
        """
        if not self.items or len(self.items) <= 0:
            raise ValueError("'items' cannot be empty")

        if self.total <= 0:
            raise ValueError("'total' must be positive")

        if self.currency is not None and self.currency not in CURRENCIES:
            raise ValueError(f"invalid 'currency' value '{self.currency}', must be one of {CURRENCIES}")

        if self.language is not None and self.language not in LANGUAGES:
            raise ValueError(f"invalid 'language' value '{self.language}', must be one of {LANGUAGES}")

        for item in self.items:
            item.validate()


@dataclass
class CustomerAddress(Serializable):
    """
    Customer address information.

    Attributes:
        address: Street address
        city: City name
        state: State or province
        zip: Postal/ZIP code
        country: Country name or code
    """

    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    country: Optional[str]


@dataclass
class CustomerInfo(Serializable):
    """
    Customer information for payment processing.

    Attributes:
        first_name: Customer's first name
        last_name: Customer's last name
        email: Customer's email address
        phone: Customer's phone number
        address: Customer's address details
    """

    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[CustomerAddress]

    def validate_for_payment(self) -> None:
        """
        Validate that required fields are present for direct payment initiation.

        The backend's InitCustomerInfo requires first_name, last_name, and email.

        Raises:
            ValueError: If any required field is missing or empty
        """
        if not self.first_name:
            raise ValueError("'first_name' is required for payment initiation")
        if not self.last_name:
            raise ValueError("'last_name' is required for payment initiation")
        if not self.email:
            raise ValueError("'email' is required for payment initiation")


@dataclass
class SessionInfo(Serializable):
    """
    Payment session information returned after order creation.

    Attributes:
        paymentSessionId: Unique payment session identifier
        paymentPageUrl: URL to redirect customer for payment
        expiresAt: Session expiration timestamp
    """

    paymentSessionId: str
    paymentPageUrl: str
    expiresAt: str


@dataclass
class PaymentCallback:
    """
    Parsed payment callback data from the gateway.

    Attributes:
        order_id: Order identifier
        total: Payment total amount
        currency: Currency code
        success: Whether payment was successful
        tx_id: Transaction identifier
        tx_meta: Additional transaction metadata
        datetime: Payment timestamp
    """

    order_id: Optional[str]
    total: Decimal
    currency: str
    success: bool
    tx_id: str
    tx_meta: Dict[str, Any]
    datetime: datetime


@dataclass
class PaymentCallbackRaw(Serializable):
    """
    Raw payment callback data from the gateway (before parsing).

    This is used internally to deserialize the callback payload.
    """

    order_id: Optional[str]
    total: str
    currency: str
    success: int
    tx_id: str
    tx_meta: Dict[str, Any]
    datetime: str
    signature: str

    def to_callback(self) -> PaymentCallback:
        """
        Convert raw callback data to parsed PaymentCallback.

        Returns:
            PaymentCallback with properly typed fields
        """
        return PaymentCallback(
            order_id=self.order_id,
            total=Decimal(self.total),
            currency=self.currency,
            success=True if self.success == 1 else False,
            tx_id=self.tx_id,
            tx_meta=self.tx_meta,
            datetime=datetime.strptime(self.datetime, "%Y-%m-%d %H:%M"),
        )


@dataclass
class CreateOrderRequest(Serializable):
    """
    Internal request model for creating an order.

    This wraps all the data needed to create a payment session.
    """

    platform_id: UUID
    currency: TCurrency
    language: TLanguage
    order_id: str
    customer: Dict[str, Any]
    items: List[Dict[str, Any]]
    total: Decimal
    response: str
    signature: str
