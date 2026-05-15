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

    Supports both generic (legacy) and generic_signed (schema 1.1) callback formats.

    Attributes:
        order_id: Order identifier
        total: Payment total amount
        currency: Currency code
        success: Whether payment was successful
        tx_id: Transaction identifier
        tx_meta: Additional transaction metadata
        datetime: Payment timestamp
        callback_type: Callback type — "payment" or "refund" (schema 1.1 only)
        session_id: Payment session UUID (schema 1.1 only)
        schema_version: Callback schema version — None for legacy, "1.1" for signed
    """

    order_id: Optional[str]
    total: Decimal
    currency: str
    success: bool
    tx_id: str
    tx_meta: Dict[str, Any]
    datetime: datetime
    callback_type: Optional[str] = None
    session_id: Optional[str] = None
    schema_version: Optional[str] = None


@dataclass
class PaymentCallbackRaw(Serializable):
    """
    Raw payment callback data from the gateway (legacy generic format).

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
class SignedPaymentCallbackRaw(Serializable):
    """
    Raw payment callback data from the gateway (generic_signed schema 1.1).
    """

    type: str
    status: str
    schema: str
    order_id: Optional[str]
    session_id: str
    event_id: str
    tx_meta: Dict[str, Any]
    timestamp: str
    currency: str
    total: Optional[str] = None
    refunded_amount: Optional[str] = None
    refunded_items: Optional[List[Dict[str, Any]]] = None
    refundable: Optional[float] = None
    signature: str = ""

    def to_callback(self) -> PaymentCallback:
        """
        Convert schema 1.1 callback data to parsed PaymentCallback.

        Returns:
            PaymentCallback with properly typed fields
        """
        amount = self.total if self.total is not None else self.refunded_amount
        return PaymentCallback(
            order_id=self.order_id,
            total=Decimal(str(amount)) if amount else Decimal("0"),
            currency=self.currency,
            success=self.status == "success",
            tx_id=self.event_id,
            tx_meta=self.tx_meta,
            datetime=datetime.fromisoformat(self.timestamp),
            callback_type=self.type,
            session_id=self.session_id,
            schema_version=self.schema,
        )


@dataclass
class PaymentOption(Serializable):
    """
    A payment provider option available for a session.

    Attributes:
        id: Payment provider identifier
        name: Payment provider display name
    """

    id: str
    name: str


@dataclass
class PaymentConfig(Serializable):
    """
    Platform payment configuration for a session.

    Attributes:
        fields_display: Fields to display (e.g., 'address_shipping', 'customer_gid')
        fields_require: Fields to require (e.g., 'phone', 'email_confirm')
        shipping_countries: Allowed shipping country codes
        skip_details_form: Whether to skip the customer details form
        allow_company: Whether to allow company-type customers
        skip_recaptcha: Whether to skip reCAPTCHA verification
    """

    fields_display: Optional[List[str]]
    fields_require: Optional[List[str]]
    shipping_countries: Optional[List[str]]
    skip_details_form: Optional[bool]
    allow_company: Optional[bool]
    skip_recaptcha: Optional[bool]


@dataclass
class SessionCustomerInfo(Serializable):
    """
    Customer information associated with a payment session.

    Attributes:
        first_name: Customer's first name
        last_name: Customer's last name
        email: Customer's email address
        phone: Customer's phone number
        address: Customer's address details
        type: Customer type ('company' or 'person')
        cgid: Customer government ID
    """

    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[CustomerAddress]
    type: Optional[str]
    cgid: Optional[str]


@dataclass
class CartItem(Serializable):
    """
    An item in a payment session shopping cart.

    Attributes:
        id: Server-assigned item identifier
        name: Item name
        description: Item description
        price: Item price
        tax: Tax amount
        tax_schema: Tax schema type (e.g., 'VAT', 'No_VAT', 'Reduced_VAT')
        quantity: Item quantity
        client_item_id: Client-provided item identifier
        refunded_quantity: Number of refunded units
    """

    id: str
    name: str
    description: Optional[str]
    price: float
    tax: float
    tax_schema: str
    quantity: int
    client_item_id: Optional[str]
    refunded_quantity: int


@dataclass
class ShoppingCart(Serializable):
    """
    Shopping cart with items and total price.

    Attributes:
        items: List of cart items
        currency: Currency code
        total_price: Total price of the cart
    """

    items: List[CartItem]
    currency: str
    total_price: float


@dataclass
class PaymentSessionDetails(Serializable):
    """
    Detailed information about a payment session.

    Returned by GET /v1/session/{session_id}.

    Attributes:
        session_id: Payment session identifier
        language_code: Current language code
        supported_languages: List of supported language codes
        payment_config: Platform payment configuration
        customer: Customer information
        shopping_cart: Shopping cart with items and total
        payment_options: Available payment providers
        terms_url: URL to the terms of service
    """

    session_id: str
    language_code: str
    supported_languages: List[str]
    payment_config: Optional[PaymentConfig]
    customer: SessionCustomerInfo
    shopping_cart: ShoppingCart
    payment_options: List[PaymentOption]
    terms_url: str


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


@dataclass
class InitCustomerInfo(Serializable):
    """
    Customer information required to initiate a payment session.

    Attributes:
        first_name: Customer's first name (required)
        last_name: Customer's last name (required)
        email: Customer's email address (required)
        phone: Customer's phone number
        address: Customer's billing address
        type: Customer type ('company' or 'person')
        cgid: Customer government ID (required for non-RS shipping)
    """

    first_name: str
    last_name: str
    email: str
    phone: Optional[str]
    address: Optional[CustomerAddress]
    type: Optional[str]
    cgid: Optional[str]

    def validate(self) -> None:
        """
        Validate customer info fields.

        Raises:
            ValueError: If any required field is missing
        """
        if not self.first_name:
            raise ValueError("'first_name' is required")
        if not self.last_name:
            raise ValueError("'last_name' is required")
        if not self.email:
            raise ValueError("'email' is required")
        if self.type is not None and self.type not in ("company", "person"):
            raise ValueError(f"invalid 'type' value '{self.type}', must be 'company' or 'person'")


@dataclass
class PaymentUrlRequest(Serializable):
    """
    Internal request model for getting a payment URL.

    This wraps the data needed to initiate a payment session.
    """

    payment_option_id: UUID
    customer: Dict[str, Any]
    address_shipping: Optional[Dict[str, Any]]
    language_code: TLanguage
    terms_accepted: bool


@dataclass
class PaymentUrlResult(Serializable):
    """
    Result of a payment URL request.

    Attributes:
        sessionId: Payment session identifier
        type: Payment gateway type ('redirect' or 'form-data')
        paymentUrl: URL to redirect the customer for payment
        metadata: Additional metadata from the payment gateway
    """

    sessionId: str
    type: Optional[str]
    paymentUrl: Optional[str]
    metadata: Optional[Dict[str, Any]]
