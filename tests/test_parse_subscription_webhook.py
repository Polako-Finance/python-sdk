"""parse_subscription_webhook: check the signature of the raw body, decode it, turn it into an event."""

import json
from uuid import UUID

import pytest

import polako.sdk as sdk
from polako.sdk import (
    ChargeFailed,
    ChargeSucceeded,
    ConfigurationError,
    DroppedExternally,
    MissingSignatureError,
    SubscriptionCancelled,
    UnknownSubscriptionEvent,
    WebhookPayloadError,
    WebhookSignatureError,
    parse_subscription_webhook,
)
from tests.factories import (
    make_cancelled_payload,
    make_charge_failed_payload,
    make_charge_succeeded_payload,
    make_dropped_externally_payload,
    make_signed_webhook,
    make_unknown_event_payload,
    sign_webhook_body,
)
from tests.generators import generate_api_key, generate_readable_string

KNOWN = [
    (make_charge_succeeded_payload, ChargeSucceeded),
    (make_charge_failed_payload, ChargeFailed),
    (make_dropped_externally_payload, DroppedExternally),
    (make_cancelled_payload, SubscriptionCancelled),
]


@pytest.fixture
def api_key() -> str:
    return generate_api_key()


@pytest.mark.parametrize("make_payload, expected", KNOWN)
def test_a_signed_webhook_becomes_its_event(make_payload, expected, api_key):
    payload = make_payload()
    body, signature = make_signed_webhook(payload, api_key)

    event = parse_subscription_webhook(body, signature, api_key)

    assert type(event) is expected
    assert event.subscription_id == UUID(payload["subscription_id"])
    assert event.merchant_subscription_ref == payload["merchant_subscription_ref"]


def test_a_text_body_works_like_bytes(api_key):
    payload = make_charge_succeeded_payload()
    body, signature = make_signed_webhook(payload, api_key)

    assert parse_subscription_webhook(body.decode(), signature, api_key) == parse_subscription_webhook(body, signature, api_key)


def test_an_unknown_event_is_returned_with_the_decoded_payload(api_key):
    payload = make_unknown_event_payload()
    body, signature = make_signed_webhook(payload, api_key)

    event = parse_subscription_webhook(body, signature, api_key)

    assert type(event) is UnknownSubscriptionEvent
    assert event.data == payload


def test_the_signature_is_checked_against_the_exact_bytes(api_key):
    payload = make_cancelled_payload()
    _, signature = make_signed_webhook(payload, api_key)
    pretty = json.dumps(payload, indent=2)

    with pytest.raises(WebhookSignatureError):
        parse_subscription_webhook(pretty, signature, api_key)


def test_a_signature_made_with_another_key_is_rejected(api_key):
    body, signature = make_signed_webhook(make_cancelled_payload(), generate_api_key())

    with pytest.raises(WebhookSignatureError):
        parse_subscription_webhook(body, signature, api_key)


def test_a_changed_body_is_rejected(api_key):
    body, signature = make_signed_webhook(make_charge_succeeded_payload(), api_key)

    with pytest.raises(WebhookSignatureError):
        parse_subscription_webhook(body.replace(b"charge_succeeded", b"cancelled"), signature, api_key)


@pytest.mark.parametrize("signature", [None, "", "  "])
def test_a_missing_signature_has_its_own_error(api_key, signature):
    body, _ = make_signed_webhook(make_cancelled_payload(), api_key)

    with pytest.raises(MissingSignatureError):
        parse_subscription_webhook(body, signature, api_key)


def test_an_empty_api_key_is_a_configuration_error():
    body, signature = make_signed_webhook(make_cancelled_payload(), generate_api_key())

    with pytest.raises(ConfigurationError):
        parse_subscription_webhook(body, signature, "")


@pytest.mark.parametrize("garbage", [b"not json at all", b"", b"{", b"\xff\xfe\x00bad"])
def test_a_forged_body_is_a_signature_error_before_anything_is_parsed(api_key, garbage):
    """An unauthenticated body is never decoded, so garbage with a wrong signature is a forgery, not bad JSON."""
    with pytest.raises(WebhookSignatureError) as exc:
        parse_subscription_webhook(garbage, generate_readable_string(64), api_key)

    assert not isinstance(exc.value, WebhookPayloadError)


@pytest.mark.parametrize("garbage", [b"not json at all", b"", b"{", b"\xff\xfe\x00bad", b"\xef\xbb"])
def test_a_correctly_signed_body_that_is_not_json_is_a_payload_error(api_key, garbage):
    signature = sign_webhook_body(garbage, api_key)

    with pytest.raises(WebhookPayloadError):
        parse_subscription_webhook(garbage, signature, api_key)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_a_correctly_signed_body_in_another_encoding_is_a_payload_error(api_key, encoding):
    """The gateway sends UTF-8 only; guessing other encodings would accept bodies it never produces."""
    body = json.dumps(make_cancelled_payload()).encode(encoding)

    with pytest.raises(WebhookPayloadError):
        parse_subscription_webhook(body, sign_webhook_body(body, api_key), api_key)


@pytest.mark.parametrize("document", [b"[]", b"7", b'"cancelled"', b"null", b"true"])
def test_a_correctly_signed_json_that_is_not_an_object_is_a_payload_error(api_key, document):
    with pytest.raises(WebhookPayloadError):
        parse_subscription_webhook(document, sign_webhook_body(document, api_key), api_key)


def test_a_signed_event_with_a_malformed_field_is_a_payload_error(api_key):
    body, signature = make_signed_webhook(make_charge_succeeded_payload(amount="abc"), api_key)

    with pytest.raises(WebhookPayloadError, match="amount"):
        parse_subscription_webhook(body, signature, api_key)


def test_a_signed_event_without_a_name_is_a_payload_error(api_key):
    payload = make_cancelled_payload()
    del payload["event"]
    body, signature = make_signed_webhook(payload, api_key)

    with pytest.raises(WebhookPayloadError, match="event"):
        parse_subscription_webhook(body, signature, api_key)


def test_the_api_key_never_appears_in_an_error(api_key):
    body, _ = make_signed_webhook(make_cancelled_payload(), api_key)

    with pytest.raises(WebhookSignatureError) as exc:
        parse_subscription_webhook(body, generate_readable_string(64), api_key)

    assert api_key not in str(exc.value) and api_key not in repr(exc.value)


def test_the_function_is_part_of_the_public_api():
    assert "parse_subscription_webhook" in sdk.__all__
