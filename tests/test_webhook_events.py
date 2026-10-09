"""Turning the payload of a subscription webhook into a typed event."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from polako.sdk import WebhookPayloadError
from polako.sdk._webhook import (
    ChargeFailed,
    ChargeSucceeded,
    DroppedExternally,
    SubscriptionCancelled,
    UnknownSubscriptionEvent,
    parse_subscription_event,
)
from tests.factories import (
    make_cancelled_payload,
    make_charge_failed_payload,
    make_charge_succeeded_payload,
    make_dropped_externally_payload,
    make_unknown_event_payload,
)
from tests.generators import generate_random_decimal, generate_readable_string

KNOWN = [
    (make_charge_succeeded_payload, ChargeSucceeded),
    (make_charge_failed_payload, ChargeFailed),
    (make_dropped_externally_payload, DroppedExternally),
    (make_cancelled_payload, SubscriptionCancelled),
]
REQUIRED = {
    "charge_succeeded": ["subscription_id", "amount", "currency", "charged_at"],
    "charge_failed": ["subscription_id", "error_class"],
    "dropped_externally": ["subscription_id"],
    "cancelled": ["subscription_id"],
}


def payload_of(event: str) -> dict:
    return {
        "charge_succeeded": make_charge_succeeded_payload,
        "charge_failed": make_charge_failed_payload,
        "dropped_externally": make_dropped_externally_payload,
        "cancelled": make_cancelled_payload,
    }[event]()


@pytest.mark.parametrize("make_payload, expected", KNOWN)
def test_each_known_event_becomes_its_class(make_payload, expected):
    payload = make_payload()

    event = parse_subscription_event(payload)

    assert type(event) is expected
    assert event.event == payload["event"]
    assert event.subscription_id == UUID(payload["subscription_id"])
    assert event.merchant_subscription_ref == payload["merchant_subscription_ref"]


def test_charge_succeeded_carries_amount_currency_and_time():
    payload = make_charge_succeeded_payload()

    event = parse_subscription_event(payload)

    assert event.amount == Decimal(payload["amount"])
    assert event.currency == payload["currency"]
    assert event.charged_at == datetime.fromisoformat(payload["charged_at"])
    assert event.charged_at.tzinfo is not None


def test_the_amount_keeps_its_decimal_places():
    amount = f"{generate_random_decimal(3, 1)}0"

    event = parse_subscription_event(make_charge_succeeded_payload(amount=amount))

    assert str(event.amount) == amount


def test_a_time_ending_in_z_is_read_as_utc():
    event = parse_subscription_event(make_charge_succeeded_payload(charged_at="2026-10-08T12:30:45Z"))

    assert event.charged_at == datetime(2026, 10, 8, 12, 30, 45, tzinfo=timezone.utc)


def test_charge_failed_carries_the_error_class():
    payload = make_charge_failed_payload()

    assert parse_subscription_event(payload).error_class == payload["error_class"]


@pytest.mark.parametrize("make_payload, expected", KNOWN)
def test_a_missing_or_null_reference_is_none(make_payload, expected):
    absent = make_payload()
    del absent["merchant_subscription_ref"]

    assert parse_subscription_event(absent).merchant_subscription_ref is None
    assert parse_subscription_event(make_payload(merchant_subscription_ref=None)).merchant_subscription_ref is None


@pytest.mark.parametrize("make_payload, expected", KNOWN)
@pytest.mark.parametrize("bad", [7, ["ref"], {"ref": "x"}])
def test_a_reference_that_is_not_text_is_rejected(make_payload, expected, bad):
    with pytest.raises(WebhookPayloadError, match="merchant_subscription_ref"):
        parse_subscription_event(make_payload(merchant_subscription_ref=bad))


@pytest.mark.parametrize("make_payload, expected", KNOWN)
def test_extra_fields_are_ignored(make_payload, expected):
    payload = make_payload(**{generate_readable_string(8): generate_readable_string(8)})

    assert type(parse_subscription_event(payload)) is expected


def test_an_unknown_event_is_returned_with_the_whole_payload():
    payload = make_unknown_event_payload()

    event = parse_subscription_event(payload)

    assert type(event) is UnknownSubscriptionEvent
    assert event.event == payload["event"]
    assert event.data == payload


def test_an_unknown_event_does_not_need_any_other_field():
    name = "evt_" + generate_readable_string(6)

    event = parse_subscription_event({"event": name})

    assert event == UnknownSubscriptionEvent(event=name, data={"event": name})


@pytest.mark.parametrize("name", ["created", "paused", "resumed", "charge_retry_scheduled"])
def test_events_the_gateway_has_but_does_not_send_here_are_unknown(name):
    assert type(parse_subscription_event(make_unknown_event_payload(event=name))) is UnknownSubscriptionEvent


@pytest.mark.parametrize(
    "payload",
    [{}, {"subscription_id": "x"}, {"event": None}, {"event": ""}, {"event": 7}, {"event": ["cancelled"]}],
)
def test_a_payload_without_a_usable_event_name_is_rejected(payload):
    with pytest.raises(WebhookPayloadError, match="event"):
        parse_subscription_event(payload)


@pytest.mark.parametrize("payload", [None, [], "cancelled", 7])
def test_a_payload_that_is_not_an_object_is_rejected(payload):
    with pytest.raises(WebhookPayloadError):
        parse_subscription_event(payload)


@pytest.mark.parametrize("event, field", [(event, field) for event, fields in REQUIRED.items() for field in fields])
def test_a_missing_required_field_names_the_field_and_the_event(event, field):
    payload = payload_of(event)
    del payload[field]

    with pytest.raises(WebhookPayloadError) as exc:
        parse_subscription_event(payload)

    assert field in str(exc.value) and event in str(exc.value)


@pytest.mark.parametrize("event, field", [(event, field) for event, fields in REQUIRED.items() for field in fields])
def test_a_null_required_field_is_rejected(event, field):
    with pytest.raises(WebhookPayloadError, match=field):
        parse_subscription_event({**payload_of(event), field: None})


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "1234", 7])
def test_a_malformed_subscription_id_is_rejected(bad):
    with pytest.raises(WebhookPayloadError, match="subscription_id"):
        parse_subscription_event(make_cancelled_payload(subscription_id=bad))


@pytest.mark.parametrize("bad", ["", "abc", "NaN", "Infinity", "1,5", 12.5])
def test_a_malformed_amount_is_rejected(bad):
    with pytest.raises(WebhookPayloadError, match="amount"):
        parse_subscription_event(make_charge_succeeded_payload(amount=bad))


@pytest.mark.parametrize("bad", ["", "yesterday", "2026-13-45T00:00:00", 1760000000])
def test_a_malformed_time_is_rejected(bad):
    with pytest.raises(WebhookPayloadError, match="charged_at"):
        parse_subscription_event(make_charge_succeeded_payload(charged_at=bad))


def test_events_are_immutable():
    event = parse_subscription_event(make_cancelled_payload())

    with pytest.raises(FrozenInstanceError):
        event.subscription_id = UUID(int=0)  # type: ignore[misc]
