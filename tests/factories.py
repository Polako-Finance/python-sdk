"""Builders for valid, randomized test data.

Each `make_*` returns a complete, valid object or payload; a test overrides only the fields it is about.
The wire payloads have the shapes the gateway produces.
"""

import hashlib
import hmac
import json
import random
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, NamedTuple, Optional, Tuple
from uuid import UUID, uuid4

from polako.sdk import (
    BillingInterval,
    ChargeAttemptStatus,
    CustomerAddress,
    CustomerInfo,
    InitCustomerInfo,
    OrderDetails,
    OrderItem,
    RefundItem,
    SubscriptionStatus,
)
from polako.sdk._constants import LANGUAGES, TAX_SCHEMAS
from polako.sdk._subscription import SubscribeRequest
from tests.generators import (
    generate_api_key,
    generate_random_decimal,
    generate_random_digit_string,
    generate_random_email,
    generate_random_host,
    generate_random_url,
    generate_readable_string,
    generate_recent_datetime,
)

READABLE_STRING_LENGTH = 12

# Currencies the gateway knows; the SDK does not restrict the value, the server does.
CURRENCIES = ("RSD", "RUB", "EUR", "USD")
LOCALES = ("sr", "en", "ru")
# ISO 4217 numeric code for RSD, as the card processor expects it in a form post.
RSD_NUMERIC_CODE = "941"


class Credentials(NamedTuple):
    """What a merchant needs to call the API: the company ID and the API key of a platform."""

    company_id: UUID
    api_key: str


def make_credentials(**overrides: Any) -> Credentials:
    values: Dict[str, Any] = {"company_id": uuid4(), "api_key": generate_api_key()}
    values.update(overrides)
    return Credentials(**values)


def make_idempotency_key() -> str:
    return str(uuid4())


def make_subscribe_args(**overrides: Any) -> Dict[str, Any]:
    """Keyword arguments for `PolakoClient.create_subscription` (without the idempotency key)."""
    args: Dict[str, Any] = {
        "customer_email": generate_random_email(),
        "amount": generate_random_decimal(3, 2),
        "currency": random.choice(CURRENCIES),
        "billing_interval": random.choice(list(BillingInterval)),
        "merchant_subscription_ref": generate_readable_string(READABLE_STRING_LENGTH),
        "success_url": generate_random_url(),
        "cancel_url": generate_random_url(),
        "error_url": generate_random_url(),
    }
    args.update(overrides)
    return args


def make_subscribe_request(**overrides: Any) -> SubscribeRequest:
    return SubscribeRequest(**make_subscribe_args(**overrides))


def make_form_post_response(**overrides: Any) -> Dict[str, Any]:
    """The `form_post` registration form: the fixed field set of the card processor."""
    form: Dict[str, Any] = {
        "type": "form_post",
        "action": generate_random_url(),
        "version": "1",
        "merchantId": generate_random_digit_string(7),
        "terminalId": "E" + generate_random_digit_string(7),
        "totalAmount": generate_random_digit_string(5),
        "currency": RSD_NUMERIC_CODE,
        "locale": random.choice(LOCALES),
        "purchaseTime": generate_recent_datetime().strftime("%y%m%d%H%M%S"),
        "orderId": generate_readable_string(READABLE_STRING_LENGTH),
        "signature": generate_readable_string(40) + "==",
    }
    form.update(overrides)
    return form


def make_hpp_form_response(**overrides: Any) -> Dict[str, Any]:
    """The `hpp_form_post` registration form: a provider-defined set of hidden fields."""
    form: Dict[str, Any] = {
        "type": "hpp_form_post",
        "action": generate_random_url(),
        "fields": {
            "orderId": generate_readable_string(READABLE_STRING_LENGTH),
            "accessToken": generate_readable_string(24),
            "merchantSig": generate_readable_string(20) + "==",
            "signedKeys": "orderId,accessToken",
        },
    }
    form.update(overrides)
    return form


def make_redirect_form_response(**overrides: Any) -> Dict[str, Any]:
    """The registration form of wire type `iframe`: just the URL to send the customer to."""
    form: Dict[str, Any] = {
        "type": "iframe",
        "action": f"https://{generate_random_host()}/redirect/{uuid4()}/{generate_readable_string(40)}",
    }
    form.update(overrides)
    return form


def make_subscribe_response(form: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
    """The 201 body of the create call; the form defaults to a `form_post`."""
    response: Dict[str, Any] = {
        "subscriptionId": str(uuid4()),
        "registrationForm": form if form is not None else make_form_post_response(),
    }
    response.update(overrides)
    return response


def encode_webhook_body(payload: Dict[str, Any]) -> bytes:
    """The bytes the gateway sends: compact JSON with sorted keys. The signature is made over exactly these."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def sign_webhook_body(body: bytes, api_key: str) -> str:
    """The `X-Signature` header value: HMAC-SHA256 hex digest of the raw body, written out independently of the SDK."""
    return hmac.new(api_key.encode(), body, hashlib.sha256).hexdigest()


def make_signed_webhook(payload: Dict[str, Any], api_key: str) -> Tuple[bytes, str]:
    """What a merchant's endpoint receives: the raw body and the `X-Signature` header value."""
    body = encode_webhook_body(payload)
    return body, sign_webhook_body(body, api_key)


def make_charge_succeeded_payload(**overrides: Any) -> Dict[str, Any]:
    """The `charge_succeeded` webhook as the gateway sends it."""
    payload: Dict[str, Any] = {
        "event": "charge_succeeded",
        "subscription_id": str(uuid4()),
        "merchant_subscription_ref": generate_readable_string(READABLE_STRING_LENGTH),
        "amount": str(generate_random_decimal(3, 2)),
        "currency": random.choice(CURRENCIES),
        "charged_at": generate_recent_datetime().isoformat(),
    }
    payload.update(overrides)
    return payload


def make_charge_failed_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event": "charge_failed",
        "subscription_id": str(uuid4()),
        "merchant_subscription_ref": generate_readable_string(READABLE_STRING_LENGTH),
        "error_class": generate_readable_string(READABLE_STRING_LENGTH),
    }
    payload.update(overrides)
    return payload


def make_dropped_externally_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event": "dropped_externally",
        "subscription_id": str(uuid4()),
        "merchant_subscription_ref": generate_readable_string(READABLE_STRING_LENGTH),
    }
    payload.update(overrides)
    return payload


def make_cancelled_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event": "cancelled",
        "subscription_id": str(uuid4()),
        "merchant_subscription_ref": generate_readable_string(READABLE_STRING_LENGTH),
    }
    payload.update(overrides)
    return payload


def make_registration_failed_payload(**overrides: Any) -> Dict[str, Any]:
    """The notification sent to `error_url`: no `event` field, `success` is 0, `order_id` equals `subscription_id`."""
    subscription_id = str(uuid4())
    payload: Dict[str, Any] = {
        "order_id": subscription_id,
        "subscription_id": subscription_id,
        "merchant_subscription_ref": generate_readable_string(READABLE_STRING_LENGTH),
        "success": 0,
        "error_message": generate_readable_string(READABLE_STRING_LENGTH),
        "provider_name": generate_readable_string(READABLE_STRING_LENGTH),
    }
    payload.update(overrides)
    return payload


def make_unknown_event_payload(**overrides: Any) -> Dict[str, Any]:
    """An event of a kind the SDK does not know, with a few fields of its own."""
    payload: Dict[str, Any] = {
        "event": "evt_" + generate_readable_string(8).lower(),
        "subscription_id": str(uuid4()),
        generate_readable_string(8): generate_readable_string(8),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class PlatformCredentials(NamedTuple):
    """What signed payment calls need: the platform ID and the secret key (the platform's API key)."""

    platform_id: UUID
    secret_key: str


def make_platform_credentials(**overrides: Any) -> PlatformCredentials:
    values: Dict[str, Any] = {"platform_id": uuid4(), "secret_key": generate_api_key()}
    values.update(overrides)
    return PlatformCredentials(**values)


def sign(source: str, secret_key: str) -> str:
    """HMAC-SHA256 hex digest, written out here so tests do not lean on the SDK's own signing code."""
    return hmac.new(secret_key.encode(), source.encode(), hashlib.sha256).hexdigest()


def make_customer_address(**overrides: Any) -> CustomerAddress:
    fields: Dict[str, Any] = {
        "address": generate_readable_string(READABLE_STRING_LENGTH),
        "city": generate_readable_string(READABLE_STRING_LENGTH),
        "state": generate_readable_string(READABLE_STRING_LENGTH),
        "zip": generate_random_digit_string(5),
        "country": generate_readable_string(READABLE_STRING_LENGTH),
    }
    fields.update(overrides)
    return CustomerAddress(**fields)


def make_customer_info(**overrides: Any) -> CustomerInfo:
    fields: Dict[str, Any] = {
        "first_name": generate_readable_string(READABLE_STRING_LENGTH),
        "last_name": generate_readable_string(READABLE_STRING_LENGTH),
        "email": generate_random_email(),
        "phone": "+" + generate_random_digit_string(11),
        "address": make_customer_address(),
    }
    fields.update(overrides)
    return CustomerInfo(**fields)


def make_init_customer_info(**overrides: Any) -> InitCustomerInfo:
    fields: Dict[str, Any] = {
        "first_name": generate_readable_string(READABLE_STRING_LENGTH),
        "last_name": generate_readable_string(READABLE_STRING_LENGTH),
        "email": generate_random_email(),
        "phone": "+" + generate_random_digit_string(11),
        "address": make_customer_address(),
        "type": random.choice(("person", "company")),
        "cgid": generate_random_digit_string(9),
    }
    fields.update(overrides)
    return InitCustomerInfo(**fields)


def make_order_item(**overrides: Any) -> OrderItem:
    fields: Dict[str, Any] = {
        "code": generate_readable_string(READABLE_STRING_LENGTH),
        "name": generate_readable_string(READABLE_STRING_LENGTH),
        "description": generate_readable_string(READABLE_STRING_LENGTH),
        "price": generate_random_decimal(3, 2),
        "quantity": random.randint(1, 5),
        "tax": random.choice(sorted(TAX_SCHEMAS)),
    }
    fields.update(overrides)
    return OrderItem(**fields)


def make_order_details(**overrides: Any) -> OrderDetails:
    """A valid order; unless given, the total is the sum of price times quantity of the items."""
    items = overrides.get("items") or [make_order_item() for _ in range(random.randint(1, 3))]
    fields: Dict[str, Any] = {
        "currency": "RSD",
        "language": random.choice(sorted(LANGUAGES)),
        "order_id": generate_readable_string(READABLE_STRING_LENGTH),
        "items": items,
        "total": sum((item.price * item.quantity for item in items), Decimal("0")),
    }
    fields.update(overrides)
    return OrderDetails(**fields)


def make_refund_item(**overrides: Any) -> RefundItem:
    fields: Dict[str, Any] = {
        "item_id": str(uuid4()),
        "refund_quantity": random.randint(1, 5),
        "item_code": generate_readable_string(READABLE_STRING_LENGTH),
    }
    fields.update(overrides)
    return RefundItem(**fields)


def make_session_info_response(**overrides: Any) -> Dict[str, Any]:
    """The body of a created payment session."""
    body: Dict[str, Any] = {
        "paymentSessionId": str(uuid4()),
        "paymentPageUrl": generate_random_url(),
        "expiresAt": generate_recent_datetime(days_ago=-1).isoformat(),
    }
    body.update(overrides)
    return body


def make_session_details_response(**overrides: Any) -> Dict[str, Any]:
    """The body of `get_session_details`: customer, cart with one item, payment options and config."""
    price = float(generate_random_decimal(3, 2))
    body: Dict[str, Any] = {
        "session_id": str(uuid4()),
        "language_code": random.choice(sorted(LANGUAGES)),
        "supported_languages": sorted(LANGUAGES),
        "payment_config": {
            "fields_display": ["address_shipping"],
            "fields_require": ["phone"],
            "shipping_countries": [generate_readable_string(2).upper()],
            "skip_details_form": False,
            "allow_company": True,
            "skip_recaptcha": False,
        },
        "customer": {
            "first_name": generate_readable_string(READABLE_STRING_LENGTH),
            "last_name": generate_readable_string(READABLE_STRING_LENGTH),
            "email": generate_random_email(),
            "phone": "+" + generate_random_digit_string(11),
            "address": make_customer_address().to_dict(),
            "type": random.choice(("person", "company")),
            "cgid": generate_random_digit_string(9),
        },
        "shopping_cart": {
            "items": [
                {
                    "id": str(uuid4()),
                    "name": generate_readable_string(READABLE_STRING_LENGTH),
                    "description": generate_readable_string(READABLE_STRING_LENGTH),
                    "price": price,
                    "tax": round(price * 0.2, 2),
                    "tax_schema": random.choice(sorted(TAX_SCHEMAS)),
                    "quantity": 1,
                    "client_item_id": generate_readable_string(READABLE_STRING_LENGTH),
                    "refunded_quantity": 0,
                }
            ],
            "currency": "RSD",
            "total_price": price,
        },
        "payment_options": [{"id": str(uuid4()), "name": generate_readable_string(READABLE_STRING_LENGTH)}],
        "terms_url": generate_random_url(),
    }
    body.update(overrides)
    return body


def make_payment_url_response(**overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "sessionId": str(uuid4()),
        "type": "redirect",
        "paymentUrl": generate_random_url(),
        "metadata": {generate_readable_string(8): generate_readable_string(8)},
    }
    body.update(overrides)
    return body


def make_order_status_response(**overrides: Any) -> Dict[str, Any]:
    price = float(generate_random_decimal(3, 2))
    body: Dict[str, Any] = {
        "session_id": str(uuid4()),
        "client_order_id": generate_readable_string(READABLE_STRING_LENGTH),
        "status": random.choice(("created", "in_process", "completed", "failed", "cancelled", "expired")),
        "created_at": generate_recent_datetime().isoformat(),
        "total": price,
        "currency": "RSD",
        "refundable": price,
        "customer_name": generate_readable_string(READABLE_STRING_LENGTH),
        "customer_email": generate_random_email(),
        "items": [
            {
                "id": str(uuid4()),
                "name": generate_readable_string(READABLE_STRING_LENGTH),
                "price": price,
                "quantity": 1,
                "refunded_quantity": 0,
                "client_item_id": generate_readable_string(READABLE_STRING_LENGTH),
            }
        ],
    }
    body.update(overrides)
    return body


def make_refund_response(**overrides: Any) -> Dict[str, Any]:
    amount = float(generate_random_decimal(3, 2))
    body: Dict[str, Any] = {
        "session_id": str(uuid4()),
        "session_status": random.choice(("REFUNDED", "PARTIALLY_REFUNDED")),
        "original_transaction_id": str(uuid4()),
        "refund_transaction_id": str(uuid4()),
        "refund_amount": amount,
        "original_amount": amount,
        "currency": "RSD",
        "refund_time": generate_recent_datetime().isoformat(),
    }
    body.update(overrides)
    return body


def make_legacy_callback_body(secret_key: str, **overrides: Any) -> Dict[str, Any]:
    """A callback in the legacy format, signed over `order_id|total|success` unless a signature is given."""
    body: Dict[str, Any] = {
        "order_id": generate_readable_string(READABLE_STRING_LENGTH),
        "total": str(generate_random_decimal(3, 2)),
        "currency": "RSD",
        "success": 1,
        "tx_id": generate_readable_string(16),
        "tx_meta": {generate_readable_string(8): generate_readable_string(8)},
        "datetime": generate_recent_datetime().strftime("%Y-%m-%d %H:%M"),
    }
    body.update(overrides)
    if "signature" not in overrides:
        body["signature"] = sign(f"{body['order_id']}|{body['total']}|{body['success']}", secret_key)
    return body


def make_signed_callback_body(secret_key: str, **overrides: Any) -> Dict[str, Any]:
    """A callback of schema 1.1, signed over `type|status|order_id|amount|currency` unless a signature is given."""
    body: Dict[str, Any] = {
        "type": "payment",
        "status": "success",
        "schema": "1.1",
        "order_id": generate_readable_string(READABLE_STRING_LENGTH),
        "session_id": str(uuid4()),
        "event_id": str(uuid4()),
        "tx_meta": {generate_readable_string(8): generate_readable_string(8)},
        "timestamp": generate_recent_datetime().replace(microsecond=0).isoformat(),
        "currency": "RSD",
        "total": str(generate_random_decimal(3, 2)),
        "merchant": {
            "name": generate_readable_string(READABLE_STRING_LENGTH),
            "pib": generate_random_digit_string(9),
            "address": generate_readable_string(READABLE_STRING_LENGTH),
        },
    }
    body.update(overrides)
    if "signature" not in overrides:
        amount = body["total"] if body.get("total") is not None else body.get("refunded_amount")
        body["signature"] = sign(f"{body['type']}|{body['status']}|{body['order_id']}|{amount}|{body['currency']}", secret_key)
    return body


def make_refund_callback_body(secret_key: str, **overrides: Any) -> Dict[str, Any]:
    """A schema 1.1 refund callback: no `total`, the refunded amount, the refunded items and what is left to refund."""
    fields: Dict[str, Any] = {
        "type": "refund",
        "total": None,
        "refunded_amount": str(generate_random_decimal(2, 2)),
        "refunded_items": [{"code": generate_readable_string(READABLE_STRING_LENGTH), "qty": random.randint(1, 5)}],
        "refundable": float(generate_random_decimal(3, 2)),
    }
    fields.update(overrides)
    return make_signed_callback_body(secret_key, **fields)


# ---------------------------------------------------------------------------
# The subscription read API: what the server sends for a list and for one subscription
# ---------------------------------------------------------------------------


def wire_moment(moment: Optional[datetime] = None) -> str:
    """A time as the server writes it: ISO 8601 with a trailing `Z` for UTC."""
    moment = moment or generate_recent_datetime(days_ago=random.randint(0, 30), hours_ago=random.randint(0, 23))
    return moment.isoformat().replace("+00:00", "Z")


def make_subscription_summary_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(uuid4()),
        "customerId": str(uuid4()),
        "customerEmail": generate_random_email(),
        "merchantSubscriptionRef": generate_readable_string(READABLE_STRING_LENGTH),
        "amount": str(generate_random_decimal(3, 2)),
        "currency": random.choice(CURRENCIES),
        "billingInterval": random.choice(list(BillingInterval)).value,
        "status": random.choice(list(SubscriptionStatus)).value,
        "nextChargeAt": wire_moment(),
        "lastChargedAt": wire_moment(),
        "createdAt": wire_moment(),
    }
    payload.update(overrides)
    return payload


def make_subscription_customer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(uuid4()),
        "externalCustomerId": generate_readable_string(READABLE_STRING_LENGTH),
        "email": generate_random_email(),
    }
    payload.update(overrides)
    return payload


def make_saved_card_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(uuid4()),
        "maskedPan": f"{generate_random_digit_string(6)}******{generate_random_digit_string(4)}",
        "cardBrand": random.choice(["VISA", "MASTERCARD", "DINACARD"]),
        "panExpiry": f"{random.randint(1, 12):02d}/{random.randint(27, 35)}",
        "status": random.choice(["active", "revoked"]),
    }
    payload.update(overrides)
    return payload


def make_charge_attempt_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(uuid4()),
        "chargeDate": generate_recent_datetime(days_ago=random.randint(0, 60)).date().isoformat(),
        "orderId": generate_readable_string(READABLE_STRING_LENGTH),
        "status": random.choice(list(ChargeAttemptStatus)).value,
        "resultCode": generate_random_digit_string(3),
        "errorClass": random.choice(["transient", "insufficient_funds", "hard_decline", None]),
        "errorMessage": generate_readable_string(READABLE_STRING_LENGTH),
        "amount": str(generate_random_decimal(3, 2)),
        "retryCount": random.randint(0, 4),
        "reconcileCount": random.randint(0, 2),
        "nextRetryAt": wire_moment(),
        "createdAt": wire_moment(),
        "updatedAt": wire_moment(),
        "paymentSessionId": str(uuid4()),
    }
    payload.update(overrides)
    return payload


def make_subscription_event_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(uuid4()),
        "eventType": random.choice(["created", "charge_succeeded", "paused", "resumed", "cancelled"]),
        "payload": {generate_readable_string(6): generate_readable_string(8)},
        "createdAt": wire_moment(),
    }
    payload.update(overrides)
    return payload


def make_subscription_detail_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": str(uuid4()),
        "customer": make_subscription_customer_payload(),
        "savedCard": make_saved_card_payload(),
        "merchantSubscriptionRef": generate_readable_string(READABLE_STRING_LENGTH),
        "amount": str(generate_random_decimal(3, 2)),
        "currency": random.choice(CURRENCIES),
        "billingInterval": random.choice(list(BillingInterval)).value,
        "status": random.choice(list(SubscriptionStatus)).value,
        "anchorAt": wire_moment(),
        "nextChargeAt": wire_moment(),
        "lastChargedAt": wire_moment(),
        "createdAt": wire_moment(),
        "failedChargeCount": random.randint(0, 3),
        "lastFailedChargeAt": wire_moment(),
        "chargeHistory": [make_charge_attempt_payload() for _ in range(random.randint(1, 3))],
        "events": [make_subscription_event_payload() for _ in range(random.randint(1, 3))],
    }
    payload.update(overrides)
    return payload


def make_subscription_page_payload(count: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    items = [make_subscription_summary_payload() for _ in range(count if count is not None else random.randint(1, 4))]
    payload: Dict[str, Any] = {
        "items": items,
        "total": len(items) + random.randint(0, 20),
        "page_size": random.randint(len(items) or 1, 50),
    }
    payload.update(overrides)
    return payload
