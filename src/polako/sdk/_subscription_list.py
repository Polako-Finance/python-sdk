"""Listing subscriptions: the subscriptions of a page and the page, as the server answers.

The values are read by ``polako.sdk._decoding``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple, Union
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
from polako.sdk._validation import (
    check_choices,
    check_limit,
    check_offset,
    check_search,
    check_sort_by,
    check_sort_order,
    check_time_bound,
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
class SubscriptionListResponse(StrictModel):
    """The list response as the server sends it (it does not say which offset the page starts at)."""

    items: Tuple[SubscriptionSummary, ...] = wire_field(many_of(SubscriptionSummary))
    total: int = wire_field(read_count)
    page_size: int = wire_field(read_count)


@dataclass(frozen=True)
class SubscriptionListQuery:
    """What the caller asks of a list: the filters, the sorting and the page, already checked and in wire form."""

    status: Optional[Tuple[str, ...]] = None
    billing_interval: Optional[Tuple[str, ...]] = None
    search: Optional[str] = None
    created_from: Optional[str] = None
    created_to: Optional[str] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
    limit: int = 10
    offset: int = 0

    @classmethod
    def from_arguments(
        cls,
        *,
        status: Any,
        billing_interval: Any,
        search: Any,
        created_from: Any,
        created_to: Any,
        sort_by: Any,
        sort_order: Any,
        limit: Any,
        offset: Any,
    ) -> "SubscriptionListQuery":
        """Check the arguments of ``list_subscriptions`` and keep them in the form that goes to the server."""
        statuses = check_choices("status", status, SubscriptionStatus)
        intervals = check_choices("billing_interval", billing_interval, BillingInterval)
        return cls(
            status=tuple(statuses) if statuses is not None else None,
            billing_interval=tuple(intervals) if intervals is not None else None,
            search=check_search(search),
            created_from=check_time_bound("created_from", created_from),
            created_to=check_time_bound("created_to", created_to),
            sort_by=check_sort_by(sort_by),
            sort_order=check_sort_order(sort_order),
            limit=check_limit(limit),
            offset=check_offset(offset),
        )

    def to_params(self) -> Dict[str, Any]:
        """The query string parameters, under the server's names; what is not asked for is left out."""
        params: Dict[str, Any] = {"limit": self.limit, "offset": self.offset}
        optional = {
            "status": list(self.status) if self.status else None,
            "billing_interval": list(self.billing_interval) if self.billing_interval else None,
            "filter": self.search,
            "date_from": self.created_from,
            "date_to": self.created_to,
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
        }
        params.update({name: value for name, value in optional.items() if value is not None})
        return params
