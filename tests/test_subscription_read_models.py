"""The models of the subscription read API, decoded from what the server sends."""

import random
import re
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from polako.sdk import (
    BillingInterval,
    ChargeAttempt,
    ChargeAttemptStatus,
    SavedCard,
    SubscriptionCustomer,
    SubscriptionDetails,
    SubscriptionEvent,
    SubscriptionPage,
    SubscriptionStatus,
    SubscriptionSummary,
)
from polako.sdk._subscription_list import SubscriptionListResponse
from tests.factories import (
    make_charge_attempt_payload,
    make_saved_card_payload,
    make_subscription_customer_payload,
    make_subscription_detail_payload,
    make_subscription_event_payload,
    make_subscription_page_payload,
    make_subscription_summary_payload,
    wire_moment,
)
from tests.generators import generate_aware_datetime, generate_naive_datetime, generate_readable_string, generate_recent_date


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def snake_case(wire_name: str) -> str:
    return re.sub("([A-Z])", lambda m: "_" + m.group(1).lower(), wire_name)


# ---------------------------------------------------------------------------
# A subscription in a list
# ---------------------------------------------------------------------------


def test_a_summary_is_read_with_real_types():
    payload = make_subscription_summary_payload()

    sub = SubscriptionSummary.from_dict(payload)

    assert sub.id == UUID(payload["id"])
    assert sub.customer_id == UUID(payload["customerId"])
    assert sub.customer_email == payload["customerEmail"]
    assert sub.merchant_subscription_ref == payload["merchantSubscriptionRef"]
    assert sub.amount == Decimal(payload["amount"]) and isinstance(sub.amount, Decimal)
    assert sub.currency == payload["currency"]
    assert sub.billing_interval is BillingInterval(payload["billingInterval"])
    assert sub.status is SubscriptionStatus(payload["status"])
    assert sub.next_charge_at == instant(payload["nextChargeAt"])
    assert sub.last_charged_at == instant(payload["lastChargedAt"])
    assert sub.created_at == instant(payload["createdAt"])


def test_optional_fields_may_be_null():
    payload = make_subscription_summary_payload(
        customerEmail=None, merchantSubscriptionRef=None, nextChargeAt=None, lastChargedAt=None
    )

    sub = SubscriptionSummary.from_dict(payload)

    assert (sub.customer_email, sub.merchant_subscription_ref, sub.next_charge_at, sub.last_charged_at) == (
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize("wire, expected", [(990, Decimal("990")), (990.5, Decimal("990.5")), ("1000.00", Decimal("1000.00"))])
def test_money_is_a_decimal_whether_sent_as_text_or_as_a_number(wire, expected):
    sub = SubscriptionSummary.from_dict(make_subscription_summary_payload(amount=wire))

    assert sub.amount == expected and isinstance(sub.amount, Decimal)


def test_times_are_timezone_aware_and_keep_the_instant():
    moment = generate_aware_datetime().astimezone(timezone.utc)
    forms = [
        moment.isoformat().replace("+00:00", "Z"),
        moment.isoformat(),
        moment.astimezone(timezone(timedelta(hours=2))).isoformat(),
    ]

    for text in forms:
        sub = SubscriptionSummary.from_dict(make_subscription_summary_payload(createdAt=text))
        assert sub.created_at.tzinfo is not None
        assert sub.created_at == moment


def test_a_time_without_a_zone_is_read_as_utc():
    naive = generate_naive_datetime()

    sub = SubscriptionSummary.from_dict(make_subscription_summary_payload(createdAt=naive.isoformat()))

    assert sub.created_at == naive.replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("status", list(SubscriptionStatus))
def test_every_known_status_is_its_member(status):
    assert SubscriptionSummary.from_dict(make_subscription_summary_payload(status=status.value)).status is status


@pytest.mark.parametrize("interval", list(BillingInterval))
def test_every_known_interval_is_its_member(interval):
    assert (
        SubscriptionSummary.from_dict(make_subscription_summary_payload(billingInterval=interval.value)).billing_interval
        is interval
    )


def test_an_unknown_status_and_interval_stay_the_raw_text():
    status, interval = generate_readable_string(10), generate_readable_string(10)

    sub = SubscriptionSummary.from_dict(make_subscription_summary_payload(status=status, billingInterval=interval))

    assert (sub.status, sub.billing_interval) == (status, interval)
    assert type(sub.status) is str and type(sub.billing_interval) is str


def test_unknown_fields_are_ignored():
    payload = make_subscription_summary_payload(**{generate_readable_string(8): generate_readable_string(8)})

    assert SubscriptionSummary.from_dict(payload).id == UUID(payload["id"])


REQUIRED_SUMMARY = ["id", "customerId", "amount", "currency", "billingInterval", "status", "createdAt"]


@pytest.mark.parametrize("field_name", REQUIRED_SUMMARY)
def test_a_missing_required_field_is_an_error(field_name):
    payload = make_subscription_summary_payload()
    del payload[field_name]

    with pytest.raises(ValueError, match=snake_case(field_name)):
        SubscriptionSummary.from_dict(payload)


@pytest.mark.parametrize("field_name", REQUIRED_SUMMARY)
def test_a_null_required_field_is_an_error(field_name):
    with pytest.raises(ValueError):
        SubscriptionSummary.from_dict(make_subscription_summary_payload(**{field_name: None}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "not-a-uuid"},
        {"id": 12345},
        {"customerId": "not-a-uuid"},
        {"amount": "abc"},
        {"amount": "NaN"},
        {"amount": "Infinity"},
        {"amount": True},
        {"amount": [1]},
        {"createdAt": "yesterday"},
        {"createdAt": 1700000000},
        {"nextChargeAt": "soon"},
        {"status": 5},
        {"billingInterval": ["monthly"]},
        {"currency": 941},
    ],
    ids=lambda o: next(iter(o)) + "=" + repr(next(iter(o.values())))[:12],
)
def test_a_value_of_the_wrong_kind_is_an_error(overrides):
    with pytest.raises(ValueError):
        SubscriptionSummary.from_dict(make_subscription_summary_payload(**overrides))


def test_a_summary_cannot_be_changed():
    sub = SubscriptionSummary.from_dict(make_subscription_summary_payload())

    with pytest.raises(FrozenInstanceError):
        sub.status = SubscriptionStatus.CANCELLED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# One subscription
# ---------------------------------------------------------------------------


def test_a_detail_is_read_with_its_customer_card_history_and_journal():
    payload = make_subscription_detail_payload()

    sub = SubscriptionDetails.from_dict(payload)

    assert sub.id == UUID(payload["id"])
    assert sub.status is SubscriptionStatus(payload["status"])
    assert sub.amount == Decimal(payload["amount"])
    assert sub.anchor_at == instant(payload["anchorAt"])
    assert sub.failed_charge_count == payload["failedChargeCount"]
    assert sub.last_failed_charge_at == instant(payload["lastFailedChargeAt"])
    assert sub.customer == SubscriptionCustomer(
        id=UUID(payload["customer"]["id"]),
        external_customer_id=payload["customer"]["externalCustomerId"],
        email=payload["customer"]["email"],
    )
    assert sub.saved_card == SavedCard(
        id=UUID(payload["savedCard"]["id"]),
        masked_pan=payload["savedCard"]["maskedPan"],
        card_brand=payload["savedCard"]["cardBrand"],
        pan_expiry=payload["savedCard"]["panExpiry"],
        status=payload["savedCard"]["status"],
    )
    assert isinstance(sub.charge_history, tuple) and isinstance(sub.events, tuple)
    assert all(isinstance(item, ChargeAttempt) for item in sub.charge_history)
    assert all(isinstance(item, SubscriptionEvent) for item in sub.events)


def test_a_detail_has_no_customer_id_or_email_of_its_own():
    sub = SubscriptionDetails.from_dict(make_subscription_detail_payload())

    assert not hasattr(sub, "customer_id") and not hasattr(sub, "customer_email")


def test_the_order_of_the_history_and_the_journal_is_kept():
    history = [make_charge_attempt_payload() for _ in range(random.randint(3, 5))]
    events = [make_subscription_event_payload() for _ in range(random.randint(3, 5))]

    sub = SubscriptionDetails.from_dict(make_subscription_detail_payload(chargeHistory=history, events=events))

    assert [str(item.id) for item in sub.charge_history] == [item["id"] for item in history]
    assert [str(item.id) for item in sub.events] == [item["id"] for item in events]


def test_empty_history_and_journal_are_empty_tuples():
    sub = SubscriptionDetails.from_dict(make_subscription_detail_payload(chargeHistory=[], events=[]))

    assert sub.charge_history == () and sub.events == ()


def test_a_subscription_without_a_card_has_none():
    assert SubscriptionDetails.from_dict(make_subscription_detail_payload(savedCard=None)).saved_card is None


def test_a_charge_is_read_with_real_types():
    payload = make_charge_attempt_payload(status="failed")

    charge = SubscriptionDetails.from_dict(make_subscription_detail_payload(chargeHistory=[payload])).charge_history[0]

    assert charge.charge_date == date.fromisoformat(payload["chargeDate"]) and type(charge.charge_date) is date
    assert charge.status is ChargeAttemptStatus.FAILED
    assert charge.order_id == payload["orderId"]
    assert charge.amount == Decimal(payload["amount"])
    assert charge.retry_count == payload["retryCount"]
    assert charge.result_code == payload["resultCode"]
    assert charge.error_class == payload["errorClass"]
    assert charge.error_message == payload["errorMessage"]
    assert charge.next_retry_at == instant(payload["nextRetryAt"])
    assert charge.created_at == instant(payload["createdAt"])
    assert charge.updated_at == instant(payload["updatedAt"])
    assert charge.payment_session_id == UUID(payload["paymentSessionId"])


def test_a_charge_may_lack_its_optional_data():
    payload = make_charge_attempt_payload(
        resultCode=None,
        errorClass=None,
        errorMessage=None,
        amount=None,
        nextRetryAt=None,
        updatedAt=None,
        paymentSessionId=None,
    )

    charge = SubscriptionDetails.from_dict(make_subscription_detail_payload(chargeHistory=[payload])).charge_history[0]

    assert (charge.result_code, charge.error_class, charge.error_message, charge.amount) == (None, None, None, None)
    assert (charge.next_retry_at, charge.updated_at, charge.payment_session_id) == (None, None, None)


def test_an_unknown_charge_status_stays_the_raw_text():
    status = generate_readable_string(9)

    charge = SubscriptionDetails.from_dict(
        make_subscription_detail_payload(chargeHistory=[make_charge_attempt_payload(status=status)])
    ).charge_history[0]

    assert charge.status == status and type(charge.status) is str


def test_an_event_keeps_its_payload():
    payload = make_subscription_event_payload(payload={"reason": generate_readable_string(7), "n": 3})

    event = SubscriptionDetails.from_dict(make_subscription_detail_payload(events=[payload])).events[0]

    assert event.event_type == payload["eventType"]
    assert event.payload == payload["payload"]
    assert event.created_at == instant(payload["createdAt"])


def test_an_event_may_have_no_payload():
    event = SubscriptionDetails.from_dict(
        make_subscription_detail_payload(events=[make_subscription_event_payload(payload=None)])
    ).events[0]

    assert event.payload is None


def test_a_card_is_only_what_may_be_shown():
    secret = generate_readable_string(24)
    card = make_saved_card_payload(token=secret, panAlias=secret)

    sub = SubscriptionDetails.from_dict(make_subscription_detail_payload(savedCard=card))

    assert secret not in repr(sub)
    assert not hasattr(sub.saved_card, "token") and not hasattr(sub.saved_card, "pan_alias")


def test_unknown_fields_of_a_detail_and_its_parts_are_ignored():
    extra = {generate_readable_string(8): generate_readable_string(8)}
    payload = make_subscription_detail_payload(
        customer=make_subscription_customer_payload(**extra),
        chargeHistory=[make_charge_attempt_payload(**extra)],
        events=[make_subscription_event_payload(**extra)],
        **extra,
    )

    assert SubscriptionDetails.from_dict(payload).id == UUID(payload["id"])


REQUIRED_DETAIL = [
    "id",
    "customer",
    "amount",
    "currency",
    "billingInterval",
    "status",
    "createdAt",
    "failedChargeCount",
    "chargeHistory",
    "events",
]


@pytest.mark.parametrize("field_name", REQUIRED_DETAIL)
def test_a_detail_without_a_required_field_is_an_error(field_name):
    payload = make_subscription_detail_payload()
    del payload[field_name]

    with pytest.raises(ValueError):
        SubscriptionDetails.from_dict(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"customer": "x"},
        {"customer": make_subscription_customer_payload(id="not-a-uuid")},
        {"customer": make_subscription_customer_payload(externalCustomerId=None)},
        {"savedCard": make_saved_card_payload(id=None)},
        {"chargeHistory": "x"},
        {"chargeHistory": [make_charge_attempt_payload(id="not-a-uuid")]},
        {"chargeHistory": [make_charge_attempt_payload(chargeDate=generate_recent_date().strftime("%d.%m.%Y"))]},
        {"chargeHistory": [make_charge_attempt_payload(retryCount="many")]},
        {"chargeHistory": [make_charge_attempt_payload(createdAt=None)]},
        {"events": "x"},
        {"events": [make_subscription_event_payload(createdAt="never")]},
        {"events": [make_subscription_event_payload(eventType=None)]},
        {"events": [make_subscription_event_payload(payload="not-an-object")]},
        {"failedChargeCount": "two"},
        {"failedChargeCount": True},
        {"failedChargeCount": -1},
        {"chargeHistory": [make_charge_attempt_payload(retryCount=-1)]},
    ],
    ids=lambda o: next(iter(o)) + "=" + repr(next(iter(o.values())))[:20],
)
def test_a_detail_with_a_malformed_part_is_an_error(overrides):
    with pytest.raises(ValueError):
        SubscriptionDetails.from_dict(make_subscription_detail_payload(**overrides))


def test_a_detail_cannot_be_changed():
    sub = SubscriptionDetails.from_dict(make_subscription_detail_payload())

    with pytest.raises(FrozenInstanceError):
        sub.status = SubscriptionStatus.CANCELLED  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        sub.customer.email = generate_readable_string(5)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# A page of a list
# ---------------------------------------------------------------------------


def test_the_list_response_is_read_into_summaries():
    payload = make_subscription_page_payload(count=3)

    wire = SubscriptionListResponse.from_dict(payload)

    assert isinstance(wire.items, tuple) and len(wire.items) == 3
    assert [str(item.id) for item in wire.items] == [item["id"] for item in payload["items"]]
    assert (wire.total, wire.page_size) == (payload["total"], payload["page_size"])


def test_an_empty_list_response():
    wire = SubscriptionListResponse.from_dict(make_subscription_page_payload(count=0, total=0))

    assert wire.items == () and wire.total == 0


@pytest.mark.parametrize("field_name", ["items", "total", "page_size"])
def test_a_list_response_without_a_required_field_is_an_error(field_name):
    payload = make_subscription_page_payload()
    del payload[field_name]

    with pytest.raises(ValueError):
        SubscriptionListResponse.from_dict(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"items": "x"},
        {"items": [make_subscription_summary_payload(id="nope")]},
        {"total": "many"},
        {"total": -1},
        {"page_size": 1.5},
    ],
    ids=["items-text", "bad-item", "total-text", "total-negative", "size-float"],
)
def test_a_malformed_list_response_is_an_error(overrides):
    with pytest.raises(ValueError):
        SubscriptionListResponse.from_dict(make_subscription_page_payload(**overrides))


def test_a_page_holds_what_the_caller_asked_for_and_cannot_be_changed():
    items = tuple(SubscriptionSummary.from_dict(make_subscription_summary_payload()) for _ in range(2))
    page = SubscriptionPage(items=items, total=7, limit=10, offset=20)

    assert (page.items, page.total, page.limit, page.offset) == (items, 7, 10, 20)
    with pytest.raises(FrozenInstanceError):
        page.total = 1  # type: ignore[misc]


def test_wire_times_use_a_trailing_z():
    assert wire_moment().endswith("Z")
