"""Verification and parsing of the webhooks the gateway sends to a merchant."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, Dict, Optional, Union
from uuid import UUID

from polako.sdk._exceptions import (
    ConfigurationError,
    MissingSignatureError,
    WebhookPayloadError,
    WebhookSignatureError,
)


@dataclass(frozen=True)
class ChargeSucceeded:
    """A scheduled charge of the subscription went through."""

    event: ClassVar[str] = "charge_succeeded"

    subscription_id: UUID
    merchant_subscription_ref: Optional[str]
    amount: Decimal
    currency: str
    charged_at: datetime


@dataclass(frozen=True)
class ChargeFailed:
    """A charge of the subscription failed. ``error_class`` says why in the gateway's terms."""

    event: ClassVar[str] = "charge_failed"

    subscription_id: UUID
    merchant_subscription_ref: Optional[str]
    error_class: str


@dataclass(frozen=True)
class DroppedExternally:
    """The customer's card agreement was revoked on the provider's side; the subscription cannot be charged."""

    event: ClassVar[str] = "dropped_externally"

    subscription_id: UUID
    merchant_subscription_ref: Optional[str]


@dataclass(frozen=True)
class SubscriptionCancelled:
    """The subscription was cancelled; there will be no further charges."""

    event: ClassVar[str] = "cancelled"

    subscription_id: UUID
    merchant_subscription_ref: Optional[str]


@dataclass(frozen=True)
class RegistrationFailed:
    """
    The customer's card registration for a subscription failed, so the subscription will never become active.

    The gateway sends this to the ``error_url`` you gave when creating the subscription. Unlike the lifecycle events it
    has no ``event`` field (``event`` is None here), and it always says ``success`` = 0 on the wire. Its ``order_id``
    field always equals ``subscription_id``; the model therefore keeps only ``subscription_id``.

    ``signature_verified`` tells whether the notification carried a valid signature. It is False only when you
    explicitly allowed unsigned notifications and the gateway sent none.
    """

    event: ClassVar[None] = None
    success: ClassVar[int] = 0

    subscription_id: UUID
    merchant_subscription_ref: Optional[str]
    error_message: Optional[str]
    provider_name: Optional[str]
    signature_verified: bool


@dataclass(frozen=True)
class UnknownSubscriptionEvent:
    """An event this version of the SDK does not know. ``data`` is the whole payload as received."""

    event: str
    data: Dict[str, Any]


SubscriptionWebhookEvent = Union[
    ChargeSucceeded, ChargeFailed, DroppedExternally, SubscriptionCancelled, UnknownSubscriptionEvent
]


def parse_subscription_webhook(body: Union[bytes, str], signature: Optional[str], api_key: str) -> SubscriptionWebhookEvent:
    """
    Check and read a subscription webhook (a charge succeeded or failed, the subscription was dropped or cancelled).

    The signature is checked first, over the raw body exactly as received: pass the bytes your framework gives you
    (for example ``await request.body()``), not JSON you have parsed and serialized again, because that changes the
    bytes and the signature no longer matches. Only a body that passed the check is decoded.

    Args:
        body: The raw request body
        signature: The value of the ``X-Signature`` header, None if the header is absent
        api_key: The API key of your platform

    Returns:
        The event: ``ChargeSucceeded``, ``ChargeFailed``, ``DroppedExternally``, ``SubscriptionCancelled``, or
        ``UnknownSubscriptionEvent`` for a kind this version of the SDK does not know

    Raises:
        ConfigurationError: If ``api_key`` is empty
        MissingSignatureError: If there is no signature
        WebhookSignatureError: If the signature does not match the body
        WebhookPayloadError: If the signed body is not a valid event
    """
    verify_webhook_signature(body, signature, api_key)

    raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError and json.JSONDecodeError are both ValueErrors
        raise WebhookPayloadError("the webhook body is not valid JSON") from None
    return parse_subscription_event(payload)


def parse_registration_failure_payload(payload: Dict[str, Any], *, signature_verified: bool) -> RegistrationFailed:
    """
    Turn the decoded body of a registration-failure notification into a ``RegistrationFailed``.

    The body must have no ``event`` field (that would make it a subscription event) and must not say ``success``
    other than 0 (the gateway always sends 0 here; a missing ``success`` is accepted).

    Raises:
        WebhookPayloadError: If the payload is not an object, has an ``event`` field, says ``success`` other than 0,
            or ``subscription_id`` is missing or malformed
    """
    what = "registration failure"
    if not isinstance(payload, dict):
        raise WebhookPayloadError("the webhook payload must be a JSON object")
    if "event" in payload:
        raise WebhookPayloadError(
            "this body has an 'event' field, so it is a subscription event, not a registration failure: "
            "read it with parse_subscription_webhook"
        )
    success = payload.get("success")
    if success is not None and not (success is False or (type(success) is int and success == 0)):
        raise WebhookPayloadError(f"{what}: 'success' must be 0, got {success!r}")

    return RegistrationFailed(
        subscription_id=_uuid(payload, what, "subscription_id"),
        merchant_subscription_ref=_optional_text(payload, what, "merchant_subscription_ref"),
        error_message=_optional_text(payload, what, "error_message"),
        provider_name=_optional_text(payload, what, "provider_name"),
        signature_verified=signature_verified,
    )


def _required(payload: Dict[str, Any], what: str, field: str) -> Any:
    value = payload.get(field)
    if value is None:
        raise WebhookPayloadError(f"{what}: required field '{field}' is missing")
    return value


def _text(payload: Dict[str, Any], what: str, field: str) -> str:
    value = _required(payload, what, field)
    if not isinstance(value, str):
        raise WebhookPayloadError(f"{what}: '{field}' must be a string")
    return value


def _uuid(payload: Dict[str, Any], what: str, field: str) -> UUID:
    value = _text(payload, what, field)
    try:
        return UUID(value)
    except ValueError:
        raise WebhookPayloadError(f"{what}: '{field}' is not a valid UUID") from None


def _amount(payload: Dict[str, Any], what: str, field: str) -> Decimal:
    value = _text(payload, what, field)
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise WebhookPayloadError(f"{what}: '{field}' is not a valid amount") from None
    if not amount.is_finite():
        raise WebhookPayloadError(f"{what}: '{field}' is not a valid amount")
    return amount


def _moment(payload: Dict[str, Any], what: str, field: str) -> datetime:
    value = _text(payload, what, field)
    try:
        # Python 3.10 does not read a trailing "Z" as UTC.
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise WebhookPayloadError(f"{what}: '{field}' is not a valid ISO 8601 time") from None


def _optional_text(payload: Dict[str, Any], what: str, field: str) -> Optional[str]:
    value = payload.get(field)
    if value is not None and not isinstance(value, str):
        raise WebhookPayloadError(f"{what}: '{field}' must be a string")
    return value


def _reference(payload: Dict[str, Any], what: str) -> Optional[str]:
    return _optional_text(payload, what, "merchant_subscription_ref")


def parse_subscription_event(payload: Dict[str, Any]) -> SubscriptionWebhookEvent:
    """
    Turn the decoded body of a subscription webhook into an event object.

    Unknown event names come back as ``UnknownSubscriptionEvent`` so that a new kind of event does not break your
    endpoint. Fields this version does not know are ignored.

    Raises:
        WebhookPayloadError: If the payload is not an object, has no event name, or a field of a known event is
            missing or malformed
    """
    if not isinstance(payload, dict):
        raise WebhookPayloadError("the webhook payload must be a JSON object")
    name = payload.get("event")
    if not isinstance(name, str) or not name:
        if "event" not in payload and "success" in payload:
            raise WebhookPayloadError(
                "the webhook payload has no 'event' name; a body with 'success' and no 'event' is a registration "
                "failure: read it with parse_registration_failed"
            )
        raise WebhookPayloadError("the webhook payload has no 'event' name")
    what = f"'{name}' event"

    if name == ChargeSucceeded.event:
        return ChargeSucceeded(
            subscription_id=_uuid(payload, what, "subscription_id"),
            merchant_subscription_ref=_reference(payload, what),
            amount=_amount(payload, what, "amount"),
            currency=_text(payload, what, "currency"),
            charged_at=_moment(payload, what, "charged_at"),
        )
    if name == ChargeFailed.event:
        return ChargeFailed(
            subscription_id=_uuid(payload, what, "subscription_id"),
            merchant_subscription_ref=_reference(payload, what),
            error_class=_text(payload, what, "error_class"),
        )
    if name == DroppedExternally.event:
        return DroppedExternally(
            subscription_id=_uuid(payload, what, "subscription_id"),
            merchant_subscription_ref=_reference(payload, what),
        )
    if name == SubscriptionCancelled.event:
        return SubscriptionCancelled(
            subscription_id=_uuid(payload, what, "subscription_id"),
            merchant_subscription_ref=_reference(payload, what),
        )
    return UnknownSubscriptionEvent(event=name, data=payload)


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
