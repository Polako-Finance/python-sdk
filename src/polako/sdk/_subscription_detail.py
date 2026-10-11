"""The detail of a subscription, as the server answers: the subscription with its customer, card, charge history and journal.

The values are read by ``polako.sdk._decoding``.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple, Union
from uuid import UUID

from polako.sdk._constants import BillingInterval, ChargeAttemptStatus, SubscriptionStatus
from polako.sdk._decoding import (
    StrictModel,
    known_or_raw,
    many_of,
    one_of,
    read_count,
    read_day,
    read_mapping,
    read_moment,
    read_money,
    read_text,
    read_uuid,
    wire_field,
)


@dataclass(frozen=True)
class SubscriptionCustomer(StrictModel):
    """The customer of a subscription."""

    id: UUID = wire_field(read_uuid)
    external_customer_id: str = wire_field(read_text, "externalCustomerId")
    email: Optional[str] = wire_field(read_text, required=False)


@dataclass(frozen=True)
class SavedCard(StrictModel):
    """Display data of the card a subscription is charged to. Never a token."""

    id: UUID = wire_field(read_uuid)
    masked_pan: Optional[str] = wire_field(read_text, "maskedPan", required=False)
    card_brand: Optional[str] = wire_field(read_text, "cardBrand", required=False)
    pan_expiry: Optional[str] = wire_field(read_text, "panExpiry", required=False)
    status: str = wire_field(read_text)


@dataclass(frozen=True)
class ChargeAttempt(StrictModel):
    """One scheduled charge of a subscription."""

    id: UUID = wire_field(read_uuid)
    charge_date: date = wire_field(read_day, "chargeDate")
    order_id: str = wire_field(read_text, "orderId")
    status: Union[ChargeAttemptStatus, str] = wire_field(known_or_raw(ChargeAttemptStatus))
    result_code: Optional[str] = wire_field(read_text, "resultCode", required=False)
    error_class: Optional[str] = wire_field(read_text, "errorClass", required=False)
    error_message: Optional[str] = wire_field(read_text, "errorMessage", required=False)
    amount: Optional[Decimal] = wire_field(read_money, required=False)
    retry_count: int = wire_field(read_count, "retryCount")
    next_retry_at: Optional[datetime] = wire_field(read_moment, "nextRetryAt", required=False)
    created_at: datetime = wire_field(read_moment, "createdAt")
    updated_at: Optional[datetime] = wire_field(read_moment, "updatedAt", required=False)
    payment_session_id: Optional[UUID] = wire_field(read_uuid, "paymentSessionId", required=False)


@dataclass(frozen=True)
class SubscriptionEvent(StrictModel):
    """One entry of the journal of a subscription."""

    id: UUID = wire_field(read_uuid)
    event_type: str = wire_field(read_text, "eventType")
    payload: Optional[Dict[str, Any]] = wire_field(read_mapping, required=False)
    created_at: datetime = wire_field(read_moment, "createdAt")


@dataclass(frozen=True)
class SubscriptionDetails(StrictModel):
    """A subscription with its customer, card, charge history (newest first) and event journal (oldest first)."""

    id: UUID = wire_field(read_uuid)
    customer: SubscriptionCustomer = wire_field(one_of(SubscriptionCustomer))
    saved_card: Optional[SavedCard] = wire_field(one_of(SavedCard), "savedCard", required=False)
    merchant_subscription_ref: Optional[str] = wire_field(read_text, "merchantSubscriptionRef", required=False)
    amount: Decimal = wire_field(read_money)
    currency: str = wire_field(read_text)
    billing_interval: Union[BillingInterval, str] = wire_field(known_or_raw(BillingInterval), "billingInterval")
    status: Union[SubscriptionStatus, str] = wire_field(known_or_raw(SubscriptionStatus))
    anchor_at: Optional[datetime] = wire_field(read_moment, "anchorAt", required=False)
    next_charge_at: Optional[datetime] = wire_field(read_moment, "nextChargeAt", required=False)
    last_charged_at: Optional[datetime] = wire_field(read_moment, "lastChargedAt", required=False)
    created_at: datetime = wire_field(read_moment, "createdAt")
    failed_charge_count: int = wire_field(read_count, "failedChargeCount")
    last_failed_charge_at: Optional[datetime] = wire_field(read_moment, "lastFailedChargeAt", required=False)
    charge_history: Tuple[ChargeAttempt, ...] = wire_field(many_of(ChargeAttempt), "chargeHistory")
    events: Tuple[SubscriptionEvent, ...] = wire_field(many_of(SubscriptionEvent))
