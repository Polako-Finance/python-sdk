"""Models for creating a subscription: the request, the response and the three kinds of registration form."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar, Dict, Union
from urllib.parse import urlparse
from uuid import UUID

from polako.sdk._constants import BillingInterval
from polako.sdk._serializable import Serializable

MERCHANT_REF_MAX_LENGTH = 128


class UnknownRegistrationFormError(ValueError):
    """The server returned a registration form of a type this SDK version does not know."""


@dataclass
class FormPost(Serializable):
    """
    A form the merchant POSTs to the card processor to start the customer's 3DS registration.

    Render it as an HTML form with ``action`` as the target and one hidden input per field.
    """

    type: ClassVar[str] = "form_post"

    action: str
    version: str
    merchant_id: str = field(metadata={"alias": "merchantId"})
    terminal_id: str = field(metadata={"alias": "terminalId"})
    total_amount: str = field(metadata={"alias": "totalAmount"})
    currency: str
    locale: str
    purchase_time: str = field(metadata={"alias": "purchaseTime"})
    order_id: str = field(metadata={"alias": "orderId"})
    signature: str


@dataclass
class HppFormPost(Serializable):
    """
    A form for a hosted payment page: ``action`` is the POST target, ``fields`` are the hidden inputs as given.

    The set of fields is defined by the provider and can differ between providers.
    """

    type: ClassVar[str] = "hpp_form_post"

    action: str
    fields: Dict[str, str]


@dataclass
class RedirectForm(Serializable):
    """
    A page the customer is redirected to for the 3DS registration (``action`` is its URL).

    On the wire this form has the type ``iframe``.
    """

    type: ClassVar[str] = "iframe"

    action: str


RegistrationForm = Union[FormPost, HppFormPost, RedirectForm]

_FORMS_BY_TYPE: Dict[str, Any] = {cls.type: cls for cls in (FormPost, HppFormPost, RedirectForm)}


def parse_registration_form(raw: Dict[str, Any]) -> RegistrationForm:
    """Pick the form class by the ``type`` field of the server response."""
    kind = raw.get("type") if isinstance(raw, dict) else None
    form_class = _FORMS_BY_TYPE.get(kind) if isinstance(kind, str) else None
    if form_class is None:
        known = ", ".join(sorted(_FORMS_BY_TYPE))
        raise UnknownRegistrationFormError(f"unknown registration form type {kind!r}, known types: {known}")
    return form_class.from_dict(raw)  # type: ignore[no-any-return]


def _check_http_url(name: str, value: str) -> None:
    parsed = urlparse(value) if isinstance(value, str) else None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"'{name}' must be a valid http or https URL")


@dataclass
class SubscribeRequest(Serializable):
    """The body of a request to create a subscription; sent to the server with camelCase names."""

    serialize_by_alias: ClassVar[bool] = True

    customer_email: str = field(metadata={"alias": "customerEmail"})
    amount: Decimal
    currency: str
    billing_interval: BillingInterval = field(metadata={"alias": "billingInterval"})
    merchant_subscription_ref: str = field(metadata={"alias": "merchantSubscriptionRef"})
    success_url: str = field(metadata={"alias": "successUrl"})
    cancel_url: str = field(metadata={"alias": "cancelUrl"})
    error_url: str = field(metadata={"alias": "errorUrl"})

    def validate(self) -> None:
        """
        Check the fields the server would reject, so the mistake shows up before a request is made.

        Raises:
            ValueError: If a field is invalid
        """
        email = self.customer_email
        if not isinstance(email, str) or "@" not in email or any(ch.isspace() for ch in email):
            raise ValueError("'customer_email' must be a valid email address")

        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount <= 0:
            raise ValueError("'amount' must be a finite Decimal greater than zero")

        if not isinstance(self.currency, str) or not self.currency:
            raise ValueError("'currency' is required")

        if not isinstance(self.billing_interval, BillingInterval):
            raise ValueError(f"'billing_interval' must be a BillingInterval, got {self.billing_interval!r}")

        ref = self.merchant_subscription_ref
        if not isinstance(ref, str) or not 1 <= len(ref) <= MERCHANT_REF_MAX_LENGTH:
            raise ValueError(f"'merchant_subscription_ref' must be 1 to {MERCHANT_REF_MAX_LENGTH} characters")

        _check_http_url("success_url", self.success_url)
        _check_http_url("cancel_url", self.cancel_url)
        _check_http_url("error_url", self.error_url)


@dataclass
class SubscribeResponse(Serializable):
    """The server response to a subscription request; names on the wire are camelCase."""

    subscription_id: UUID = field(metadata={"alias": "subscriptionId", "decode": UUID})
    registration_form: RegistrationForm = field(metadata={"alias": "registrationForm", "decode": parse_registration_form})


@dataclass(frozen=True)
class SubscriptionCreated:
    """
    The result of creating a subscription.

    Attributes:
        subscription_id: The id of the new subscription
        registration_form: The form that sends the customer through the card registration (3DS)
        idempotency_key: The key the request was sent with. Sending the same request again with this key
            returns the same subscription, so keep it until the subscription is confirmed
    """

    subscription_id: UUID
    registration_form: RegistrationForm
    idempotency_key: str
