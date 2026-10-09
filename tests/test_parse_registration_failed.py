"""parse_registration_failed with a signature: check the raw body, decode it, read the failure."""

import json
from uuid import UUID

import pytest

import polako.sdk as sdk
from polako.sdk import (
    ConfigurationError,
    MissingSignatureError,
    RegistrationFailed,
    WebhookPayloadError,
    WebhookSignatureError,
    parse_registration_failed,
)
from tests.factories import make_cancelled_payload, make_registration_failed_payload, make_signed_webhook, sign_webhook_body
from tests.generators import generate_api_key, generate_readable_string


@pytest.fixture
def api_key() -> str:
    return generate_api_key()


def test_a_signed_notification_becomes_a_verified_failure(api_key):
    payload = make_registration_failed_payload()
    body, signature = make_signed_webhook(payload, api_key)

    failed = parse_registration_failed(body, signature, api_key)

    assert type(failed) is RegistrationFailed
    assert failed.signature_verified is True
    assert failed.subscription_id == UUID(payload["subscription_id"])
    assert failed.merchant_subscription_ref == payload["merchant_subscription_ref"]
    assert failed.error_message == payload["error_message"]
    assert failed.provider_name == payload["provider_name"]


def test_a_text_body_works_like_bytes(api_key):
    body, signature = make_signed_webhook(make_registration_failed_payload(), api_key)

    assert parse_registration_failed(body.decode(), signature, api_key) == parse_registration_failed(body, signature, api_key)


def test_the_signature_is_checked_against_the_exact_bytes(api_key):
    payload = make_registration_failed_payload()
    _, signature = make_signed_webhook(payload, api_key)

    with pytest.raises(WebhookSignatureError):
        parse_registration_failed(json.dumps(payload, indent=2), signature, api_key)


def test_a_signature_made_with_another_key_is_rejected(api_key):
    body, signature = make_signed_webhook(make_registration_failed_payload(), generate_api_key())

    with pytest.raises(WebhookSignatureError):
        parse_registration_failed(body, signature, api_key)


def test_a_changed_body_is_rejected(api_key):
    payload = make_registration_failed_payload()
    body, signature = make_signed_webhook(payload, api_key)

    with pytest.raises(WebhookSignatureError):
        parse_registration_failed(body.replace(payload["error_message"].encode(), b"changed"), signature, api_key)


@pytest.mark.parametrize("signature", [None, "", "  "])
def test_a_missing_signature_has_its_own_error(api_key, signature):
    body, _ = make_signed_webhook(make_registration_failed_payload(), api_key)

    with pytest.raises(MissingSignatureError):
        parse_registration_failed(body, signature, api_key)


def test_an_empty_api_key_is_a_configuration_error():
    body, signature = make_signed_webhook(make_registration_failed_payload(), generate_api_key())

    with pytest.raises(ConfigurationError):
        parse_registration_failed(body, signature, "")


@pytest.mark.parametrize("garbage", [b"not json at all", b"", b"{", b"\xff\xfe\x00bad"])
def test_a_forged_body_is_a_signature_error_before_anything_is_parsed(api_key, garbage):
    with pytest.raises(WebhookSignatureError) as exc:
        parse_registration_failed(garbage, generate_readable_string(64), api_key)

    assert not isinstance(exc.value, WebhookPayloadError)


@pytest.mark.parametrize("garbage", [b"not json at all", b"", b"{", b"\xff\xfe\x00bad", b"\xef\xbb"])
def test_a_correctly_signed_body_that_is_not_json_is_a_payload_error(api_key, garbage):
    with pytest.raises(WebhookPayloadError):
        parse_registration_failed(garbage, sign_webhook_body(garbage, api_key), api_key)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_a_correctly_signed_body_in_another_encoding_is_a_payload_error(api_key, encoding):
    body = json.dumps(make_registration_failed_payload()).encode(encoding)

    with pytest.raises(WebhookPayloadError):
        parse_registration_failed(body, sign_webhook_body(body, api_key), api_key)


@pytest.mark.parametrize("document", [b"[]", b"7", b'"failed"', b"null", b"true"])
def test_a_correctly_signed_json_that_is_not_an_object_is_a_payload_error(api_key, document):
    with pytest.raises(WebhookPayloadError):
        parse_registration_failed(document, sign_webhook_body(document, api_key), api_key)


def test_a_signed_subscription_event_is_not_a_registration_failure(api_key):
    body, signature = make_signed_webhook(make_cancelled_payload(), api_key)

    with pytest.raises(WebhookPayloadError, match="parse_subscription_webhook"):
        parse_registration_failed(body, signature, api_key)


@pytest.mark.parametrize("success", [1, True, "0"])
def test_a_signed_body_that_does_not_say_success_zero_is_rejected(api_key, success):
    body, signature = make_signed_webhook(make_registration_failed_payload(success=success), api_key)

    with pytest.raises(WebhookPayloadError, match="success"):
        parse_registration_failed(body, signature, api_key)


def test_a_signed_body_without_subscription_id_is_rejected(api_key):
    payload = make_registration_failed_payload()
    del payload["subscription_id"]
    body, signature = make_signed_webhook(payload, api_key)

    with pytest.raises(WebhookPayloadError, match="subscription_id"):
        parse_registration_failed(body, signature, api_key)


def test_the_api_key_never_appears_in_an_error(api_key):
    body, _ = make_signed_webhook(make_registration_failed_payload(), api_key)

    with pytest.raises(WebhookSignatureError) as exc:
        parse_registration_failed(body, generate_readable_string(64), api_key)

    assert api_key not in str(exc.value) and api_key not in repr(exc.value)


def test_the_function_is_part_of_the_public_api():
    assert "parse_registration_failed" in sdk.__all__
