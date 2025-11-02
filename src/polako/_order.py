from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from polako._constants import CURRENCIES, LANGUAGES, TAX_SCHEMAS, TCurrency, TLanguage, TTaxSchema
from polako._serializable import Serializable


@dataclass
class OrderItem(Serializable):
    code: Optional[str]
    name: str
    description: Optional[str]
    price: Decimal
    quantity: int
    tax: Optional[TTaxSchema]

    def validate(self):
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
    currency: Optional[TCurrency]
    language: Optional[TLanguage]
    order_id: Optional[str]
    items: List[OrderItem]
    total: Decimal

    def validate(self):
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
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    country: Optional[str]


@dataclass
class CustomerInfo(Serializable):
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[CustomerAddress]


@dataclass
class SessionInfo(Serializable):
    paymentSessionId: str
    paymentPageUrl: str
    expiresAt: str


@dataclass
class PaymentCallback:
    order_id: Optional[str]
    total: Decimal
    currency: str
    success: bool
    tx_id: str
    tx_meta: Dict[str, Any]
    datetime: datetime


@dataclass
class PaymentCallbackRaw(Serializable):
    order_id: Optional[str]
    total: str
    currency: str
    success: int
    tx_id: str
    tx_meta: Dict[str, Any]
    datetime: str
    signature: str

    def to_callback(self) -> PaymentCallback:
        return PaymentCallback(
            order_id=self.order_id,
            total=Decimal(self.total),
            currency=self.currency,
            success=True if self.success == 1 else False,
            tx_id=self.tx_id,
            tx_meta=self.tx_meta,
            datetime=datetime.strptime(self.datetime, "%Y-%m-%d %H:%M"),
        )
