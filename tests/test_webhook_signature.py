"""Verifying the signature of a webhook over its raw body."""

import hmac
import json

import pytest

from polako.sdk import ConfigurationError, MissingSignatureError, WebhookSignatureError
from polako.sdk._webhook import verify_webhook_signature
from tests.factories import encode_webhook_body, sign_webhook_body
from tests.generators import generate_api_key, generate_readable_string


@pytest.fixture
def api_key() -> str:
    return generate_api_key()


@pytest.fixture
def payload() -> dict:
    return {generate_readable_string(8): generate_readable_string(12) for _ in range(3)}


@pytest.fixture
def body(payload) -> bytes:
    return encode_webhook_body(payload)


def test_a_correct_signature_passes(body, api_key):
    verify_webhook_signature(body, sign_webhook_body(body, api_key), api_key)


def test_the_body_may_be_given_as_text(body, api_key):
    verify_webhook_signature(body.decode(), sign_webhook_body(body, api_key), api_key)


def test_a_text_body_is_hashed_exactly_as_it_is(api_key):
    """Spaces and non-ASCII characters inside the body are part of what was signed."""
    text = f"{generate_readable_string(6)} {generate_readable_string(6)} éя"
    raw = text.encode("utf-8")

    verify_webhook_signature(text, sign_webhook_body(raw, api_key), api_key)
    verify_webhook_signature(raw, sign_webhook_body(raw, api_key), api_key)


def test_the_hex_digest_may_be_upper_case_or_padded(body, api_key):
    signature = sign_webhook_body(body, api_key)

    verify_webhook_signature(body, signature.upper(), api_key)
    verify_webhook_signature(body, f"  {signature}\n", api_key)


def test_a_signature_of_another_key_is_rejected(body, api_key):
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(body, sign_webhook_body(body, generate_api_key()), api_key)


def test_a_changed_body_is_rejected(body, api_key):
    signature = sign_webhook_body(body, api_key)

    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(body + b" ", signature, api_key)


def test_a_reserialized_body_is_rejected(payload, body, api_key):
    """Parsing the JSON and dumping it again changes the bytes, so the signature no longer fits."""
    signature = sign_webhook_body(body, api_key)
    reserialized = json.dumps(payload, indent=2).encode()

    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(reserialized, signature, api_key)


@pytest.mark.parametrize("signature", [None, "", "   "])
def test_a_missing_signature_has_its_own_error(body, api_key, signature):
    with pytest.raises(MissingSignatureError):
        verify_webhook_signature(body, signature, api_key)


def test_a_missing_signature_is_also_a_signature_error():
    assert issubclass(MissingSignatureError, WebhookSignatureError)


@pytest.mark.parametrize("garbage", ["not hex at all", "0" * 64, "ключ", "\x00\xff"])
def test_a_garbage_signature_is_a_signature_error_not_a_crash(body, api_key, garbage):
    with pytest.raises(WebhookSignatureError):
        verify_webhook_signature(body, garbage, api_key)


def test_a_forgery_is_never_an_assertion_error():
    assert not issubclass(WebhookSignatureError, AssertionError)


def test_an_empty_api_key_is_a_configuration_error(body):
    with pytest.raises(ConfigurationError):
        verify_webhook_signature(body, sign_webhook_body(body, generate_api_key()), "")


def test_the_comparison_is_constant_time(body, api_key, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))

    verify_webhook_signature(body, sign_webhook_body(body, api_key), api_key)

    assert len(calls) == 1


def test_the_api_key_never_appears_in_the_error(body, api_key):
    with pytest.raises(WebhookSignatureError) as exc:
        verify_webhook_signature(body, generate_readable_string(64), api_key)

    assert api_key not in str(exc.value) and api_key not in repr(exc.value)
