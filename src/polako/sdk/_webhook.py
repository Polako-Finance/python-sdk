"""Verification and parsing of the webhooks the gateway sends to a merchant."""

import hashlib
import hmac
from typing import Optional, Union

from polako.sdk._exceptions import ConfigurationError, MissingSignatureError, WebhookSignatureError


def verify_webhook_signature(body: Union[bytes, str], signature: Optional[str], api_key: str) -> None:
    """
    Check that a webhook was signed with your API key.

    The gateway signs the raw request body: HMAC-SHA256 with your API key, hex digest in the ``X-Signature`` header.
    Pass the body exactly as it was received. A body that was parsed as JSON and serialized again has different bytes
    and will not match.

    Args:
        body: The raw request body
        signature: The value of the ``X-Signature`` header, None if the header is absent
        api_key: The API key of your platform

    Raises:
        ConfigurationError: If ``api_key`` is empty
        MissingSignatureError: If there is no signature
        WebhookSignatureError: If the signature does not match the body
    """
    if not api_key:
        raise ConfigurationError("'api_key' is required to verify a webhook signature")
    if signature is None or not signature.strip():
        raise MissingSignatureError("the webhook has no signature (the X-Signature header is missing or empty)")

    raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    expected = hmac.new(api_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    received = signature.strip().lower()

    if not hmac.compare_digest(expected.encode("ascii"), received.encode("utf-8", errors="replace")):
        raise WebhookSignatureError("the webhook signature does not match its body")
