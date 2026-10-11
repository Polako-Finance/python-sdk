"""The notification about a failed card registration: fields, the explicit no-event and success rules."""

from dataclasses import FrozenInstanceError, fields
from uuid import UUID

import pytest

from polako.sdk import WebhookPayloadError
from polako.sdk._webhook import (
    ChargeFailed,
    ChargeSucceeded,
    DroppedExternally,
    RegistrationFailed,
    SubscriptionCancelled,
    parse_registration_failure_payload,
    parse_subscription_event,
)
from tests.factories import (
    make_cancelled_payload,
    make_charge_succeeded_payload,
    make_registration_failed_payload,
)
from tests.generators import generate_readable_string

LIFECYCLE = [ChargeSucceeded, ChargeFailed, DroppedExternally, SubscriptionCancelled]
OPTIONAL_TEXT = ["merchant_subscription_ref", "error_message", "provider_name"]


def parse(payload, verified=True):
    return parse_registration_failure_payload(payload, signature_verified=verified)


def test_the_fields_are_read_from_the_payload():
    payload = make_registration_failed_payload()

    failed = parse(payload)

    assert failed.subscription_id == UUID(payload["subscription_id"])
    assert failed.merchant_subscription_ref == payload["merchant_subscription_ref"]
    assert failed.error_message == payload["error_message"]
    assert failed.provider_name == payload["provider_name"]


@pytest.mark.parametrize("verified", [True, False])
def test_the_signature_flag_is_passed_through(verified):
    assert parse(make_registration_failed_payload(), verified).signature_verified is verified


def test_the_model_says_it_has_no_event_and_no_success_to_vary():
    assert RegistrationFailed.event is None
    assert RegistrationFailed.success == 0


def test_every_lifecycle_event_has_a_name_unlike_the_registration_failure():
    names = [cls.event for cls in LIFECYCLE]

    assert all(isinstance(name, str) and name for name in names)
    assert len(set(names)) == len(names)


def test_order_id_is_not_kept_because_it_always_equals_subscription_id():
    assert "order_id" not in {f.name for f in fields(RegistrationFailed)}


@pytest.mark.parametrize("field", OPTIONAL_TEXT)
def test_an_optional_text_field_may_be_missing_or_null(field):
    absent = make_registration_failed_payload()
    del absent[field]

    assert getattr(parse(absent), field) is None
    assert getattr(parse(make_registration_failed_payload(**{field: None})), field) is None


@pytest.mark.parametrize("field", OPTIONAL_TEXT)
@pytest.mark.parametrize("bad", [7, ["x"], {"x": 1}, True])
def test_an_optional_text_field_that_is_not_text_is_rejected(field, bad):
    with pytest.raises(WebhookPayloadError, match=field):
        parse(make_registration_failed_payload(**{field: bad}))


def test_subscription_id_is_required():
    payload = make_registration_failed_payload()
    del payload["subscription_id"]

    with pytest.raises(WebhookPayloadError, match="subscription_id"):
        parse(payload)
    with pytest.raises(WebhookPayloadError, match="subscription_id"):
        parse(make_registration_failed_payload(subscription_id=None))


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "1234", 7])
def test_a_malformed_subscription_id_is_rejected(bad):
    with pytest.raises(WebhookPayloadError, match="subscription_id"):
        parse(make_registration_failed_payload(subscription_id=bad))


def test_extra_fields_are_ignored():
    payload = make_registration_failed_payload(**{generate_readable_string(8): generate_readable_string(8)})

    assert type(parse(payload)) is RegistrationFailed


def test_the_result_is_immutable():
    with pytest.raises(FrozenInstanceError):
        parse(make_registration_failed_payload()).subscription_id = UUID(int=0)  # type: ignore[misc]


@pytest.mark.parametrize("payload", [None, [], "failed", 7])
def test_a_payload_that_is_not_an_object_is_rejected(payload):
    with pytest.raises(WebhookPayloadError):
        parse(payload)


@pytest.mark.parametrize("value", ["charge_succeeded", "", None, 7])
def test_a_payload_with_an_event_field_is_not_a_registration_failure(value):
    with pytest.raises(WebhookPayloadError, match="parse_subscription_webhook"):
        parse(make_registration_failed_payload(event=value))


@pytest.mark.parametrize("success", [0, False])
def test_success_zero_is_the_normal_failure(success):
    assert type(parse(make_registration_failed_payload(success=success))) is RegistrationFailed


def test_a_missing_or_null_success_is_accepted():
    absent = make_registration_failed_payload()
    del absent["success"]

    assert type(parse(absent)) is RegistrationFailed
    assert type(parse(make_registration_failed_payload(success=None))) is RegistrationFailed


@pytest.mark.parametrize("success", [1, True, 2, -1, 0.0, "0", "false", "", [], {}, [0]])
def test_a_success_that_is_not_zero_is_not_a_failure(success):
    with pytest.raises(WebhookPayloadError, match="success"):
        parse(make_registration_failed_payload(success=success))


def test_a_registration_failure_sent_to_the_lifecycle_parser_points_to_the_right_function():
    with pytest.raises(WebhookPayloadError, match="parse_registration_failed"):
        parse_subscription_event(make_registration_failed_payload())


def test_a_body_with_neither_event_nor_success_keeps_the_plain_message():
    with pytest.raises(WebhookPayloadError) as exc:
        parse_subscription_event({"subscription_id": make_cancelled_payload()["subscription_id"]})

    assert "parse_registration_failed" not in str(exc.value)
    assert "event" in str(exc.value)


def test_a_lifecycle_event_is_unaffected_by_the_hint():
    assert type(parse_subscription_event(make_charge_succeeded_payload())) is ChargeSucceeded
