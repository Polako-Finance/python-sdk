"""Listing subscriptions: the subscriptions of a page and the page, as the server answers.

The values are read by ``polako.sdk._decoding``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple, Union
from uuid import UUID

from polako.sdk._constants import BillingInterval, SubscriptionStatus
from polako.sdk._decoding import (
    StrictModel,
    known_or_raw,
    many_of,
    read_count,
    read_moment,
    read_money,
    read_text,
    read_uuid,
    wire_field,
)


@dataclass(frozen=True)
class SubscriptionSummary(StrictModel):
    """A subscription as it appears in a list."""

    id: UUID = wire_field(read_uuid)
    customer_id: UUID = wire_field(read_uuid, "customerId")
    customer_email: Optional[str] = wire_field(read_text, "customerEmail", required=False)
    merchant_subscription_ref: Optional[str] = wire_field(read_text, "merchantSubscriptionRef", required=False)
    amount: Decimal = wire_field(read_money)
    currency: str = wire_field(read_text)
    billing_interval: Union[BillingInterval, str] = wire_field(known_or_raw(BillingInterval), "billingInterval")
    status: Union[SubscriptionStatus, str] = wire_field(known_or_raw(SubscriptionStatus))
    next_charge_at: Optional[datetime] = wire_field(read_moment, "nextChargeAt", required=False)
    last_charged_at: Optional[datetime] = wire_field(read_moment, "lastChargedAt", required=False)
    created_at: datetime = wire_field(read_moment, "createdAt")


@dataclass(frozen=True)
class SubscriptionPage:
    """
    One page of a subscription list.

    Attributes:
        items: The subscriptions on this page
        total: How many subscriptions match the filters in all
        limit: The page size
        offset: How many matching subscriptions were skipped before this page
    """

    items: Tuple[SubscriptionSummary, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class _PageWire(StrictModel):
    """The list response as the server sends it (it does not say which offset the page starts at)."""

    items: Tuple[SubscriptionSummary, ...] = wire_field(many_of(SubscriptionSummary))
    total: int = wire_field(read_count)
    page_size: int = wire_field(read_count)
