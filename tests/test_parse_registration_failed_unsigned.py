"""parse_registration_failed with allow_unsigned: a missing signature is accepted, a wrong one never is."""

import dataclasses
import json

import pytest

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

NO_SIGNATURE = [None, "", "   "]


@pytest.fixture
def api_key() -> str:
    return generate_api_key()


@pytest.fixture
def payload() -> dict:
    return make_registration_failed_payload()


@pytest.fixture
def body(payload, api_key) -> bytes:
    return make_signed_webhook(payload, api_key)[0]


@pytest.mark.parametrize("signature", NO_SIGNATURE)
def test_an_unsigned_notification_is_accepted_when_allowed_and_flagged_unverified(body, payload, api_key, signature):
    failed = parse_registration_failed(body, signature, api_key, allow_unsigned=True)

    assert type(failed) is RegistrationFailed
    assert failed.signature_verified is False
    assert str(failed.subscription_id) == payload["subscription_id"]
    assert failed.error_message == payload["error_message"]


def test_an_unsigned_notification_differs_from_the_signed_one_only_by_the_flag(body, api_key):
    signed = parse_registration_failed(body, sign_webhook_body(body, api_key), api_key, allow_unsigned=True)
    unsigned = parse_registration_failed(body, None, api_key, allow_unsigned=True)

    assert signed.signature_verified is True
    assert dataclasses.replace(signed, signature_verified=False) == unsigned


def test_a_text_body_is_accepted_unsigned_too(body, api_key):
    assert parse_registration_failed(body.decode(), None, api_key, allow_unsigned=True).signature_verified is False


@pytest.mark.parametrize("signature", NO_SIGNATURE)
def test_an_unsigned_notification_is_rejected_by_default(body, api_key, signature):
    with pytest.raises(MissingSignatureError):
        parse_registration_failed(body, signature, api_key)
    with pytest.raises(MissingSignatureError):
        parse_registration_failed(body, signature, api_key, allow_unsigned=False)


def test_the_flag_can_only_be_given_by_keyword(body, api_key):
    with pytest.raises(TypeError):
        parse_registration_failed(body, None, api_key, True)  # type: ignore[misc]


def test_a_correct_signature_is_verified_even_when_unsigned_is_allowed(body, api_key):
    failed = parse_registration_failed(body, sign_webhook_body(body, api_key), api_key, allow_unsigned=True)

    assert failed.signature_verified is True


def test_a_wrong_signature_is_never_accepted_even_when_unsigned_is_allowed(body, api_key):
    with pytest.raises(WebhookSignatureError) as exc:
        parse_registration_failed(body, generate_readable_string(64), api_key, allow_unsigned=True)

    assert not isinstance(exc.value, MissingSignatureError)


def test_a_signature_of_another_key_is_never_accepted(payload, api_key):
    body, signature = make_signed_webhook(payload, generate_api_key())

    with pytest.raises(WebhookSignatureError):
        parse_registration_failed(body, signature, api_key, allow_unsigned=True)


def test_a_changed_body_with_the_old_signature_is_never_accepted(payload, api_key):
    body, signature = make_signed_webhook(payload, api_key)

    with pytest.raises(WebhookSignatureError):
        parse_registration_failed(
            body.replace(payload["error_message"].encode(), b"changed"), signature, api_key, allow_unsigned=True
        )


@pytest.mark.parametrize("garbage", [b"not json at all", b"", b"{", b"\xff\xfe\x00bad"])
def test_a_forged_body_with_a_wrong_signature_is_a_signature_error_not_a_payload_error(garbage, api_key):
    with pytest.raises(WebhookSignatureError):
        parse_registration_failed(garbage, generate_readable_string(64), api_key, allow_unsigned=True)


@pytest.mark.parametrize("garbage", [b"not json at all", b"", b"{", b"\xff\xfe\x00bad"])
def test_an_unsigned_body_that_is_not_json_is_a_payload_error(garbage, api_key):
    with pytest.raises(WebhookPayloadError):
        parse_registration_failed(garbage, None, api_key, allow_unsigned=True)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_an_unsigned_body_in_another_encoding_is_a_payload_error(payload, api_key, encoding):
    with pytest.raises(WebhookPayloadError):
        parse_registration_failed(json.dumps(payload).encode(encoding), None, api_key, allow_unsigned=True)


@pytest.mark.parametrize("document", [b"[]", b"7", b'"failed"', b"null"])
def test_an_unsigned_json_that_is_not_an_object_is_a_payload_error(document, api_key):
    with pytest.raises(WebhookPayloadError):
        parse_registration_failed(document, None, api_key, allow_unsigned=True)


def test_an_unsigned_subscription_event_is_still_not_a_registration_failure(api_key):
    body = make_signed_webhook(make_cancelled_payload(), api_key)[0]

    with pytest.raises(WebhookPayloadError, match="parse_subscription_webhook"):
        parse_registration_failed(body, None, api_key, allow_unsigned=True)


def test_an_unsigned_body_is_validated_like_a_signed_one(api_key):
    bad_success = make_signed_webhook(make_registration_failed_payload(success=1), api_key)[0]
    no_id = make_registration_failed_payload()
    del no_id["subscription_id"]

    with pytest.raises(WebhookPayloadError, match="success"):
        parse_registration_failed(bad_success, None, api_key, allow_unsigned=True)
    with pytest.raises(WebhookPayloadError, match="subscription_id"):
        parse_registration_failed(make_signed_webhook(no_id, api_key)[0], None, api_key, allow_unsigned=True)


@pytest.mark.parametrize("signature", [None, "signed"])
def test_an_empty_api_key_is_a_configuration_error_even_when_unsigned_is_allowed(body, signature):
    with pytest.raises(ConfigurationError):
        parse_registration_failed(body, signature, "", allow_unsigned=True)
