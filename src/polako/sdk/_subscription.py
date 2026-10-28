"""Models for creating a subscription: the request, the response and the three kinds of registration form."""

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from typing import Any, ClassVar, Dict, Type, TypeVar, Union
from urllib.parse import urlparse
from uuid import UUID

from polako.sdk._constants import BillingInterval
from polako.sdk._decoding import StrictModel, read_text, read_text_mapping, read_uuid, refuse_missing, wire_field
from polako.sdk._exceptions import InvalidArgumentError
from polako.sdk._serializable import Serializable

MERCHANT_REF_MAX_LENGTH = 128

_Form = TypeVar("_Form", bound="_RegistrationFormBase")


class UnknownRegistrationFormError(ValueError):
    """The server returned a registration form of a type this SDK version does not know."""


@dataclass
class _RegistrationFormBase(Serializable):
    """
    What the three registration forms share.

    ``type`` is a field, the first one, so every serializer that walks the fields keeps it (``dataclasses.asdict`` and
    a web framework's encoder too, with the Python names). ``to_dict()`` and ``to_json()`` give the form as the gateway
    sent it, ``type`` first and the wire names: the shape a page takes when it sends the customer on with the
    JavaScript SDK. Each kind gives its own type as the default; a form is made, or read back, only with its own type
    or none (a dict without one, as 0.2.2's ``to_dict()`` gave, is read as the model's own kind if it holds only that
    model's fields).

    Read from the gateway (``from_dict``), every field must be there and be text (an ``hpp_form_post`` may have no
    fields, as the gateway allows; the JavaScript SDK refuses such a form). A form built or changed by hand is checked
    only for its ``type`` and for missing values, when it is made.
    """

    serialize_by_alias: ClassVar[bool] = True

    type: str = field(default="", kw_only=True)

    @classmethod
    def _own_type(cls) -> str:
        return str(cls.__dataclass_fields__["type"].default)  # type: ignore[attr-defined]

    @classmethod
    def from_dict(cls: Type[_Form], data: dict) -> _Form:
        """
        Read a form; a dict without a ``type`` is read as this model's own kind, if it holds only this model's fields.

        Raises:
            ValueError: If the form is of another kind (by its ``type``, or without one, by its fields), or half a form
        """
        if data.get("type") is None:
            known = {name for f in dataclass_fields(cls) for name in (f.name, f.metadata.get("alias")) if name}
            foreign = sorted(set(data) - known)
            if foreign:
                raise ValueError(f"{cls.__name__}: a form without a type, with fields of another kind: {foreign}")
            data = {**data, "type": cls._own_type()}  # type: ignore[attr-defined]
        return super().from_dict(data)  # type: ignore[misc]

    def __post_init__(self) -> None:
        own = self._own_type()
        if self.type != own:
            raise ValueError(f"{self.__class__.__name__}: the type of this form is {own!r}, not {self.type!r}")
        refuse_missing(self, every_field=True)


@dataclass
class FormPost(_RegistrationFormBase):
    """
    A form the merchant POSTs to the card processor to start the customer's 3DS registration.

    Render it as an HTML form with ``action`` as the target and one hidden input per field.
    """

    type: str = field(default="form_post", kw_only=True)

    action: str = wire_field(read_text)
    version: str = wire_field(read_text)
    merchant_id: str = wire_field(read_text, "merchantId")
    terminal_id: str = wire_field(read_text, "terminalId")
    total_amount: str = wire_field(read_text, "totalAmount")
    currency: str = wire_field(read_text)
    locale: str = wire_field(read_text)
    purchase_time: str = wire_field(read_text, "purchaseTime")
    order_id: str = wire_field(read_text, "orderId")
    signature: str = wire_field(read_text)


@dataclass
class HppFormPost(_RegistrationFormBase):
    """
    A form for a hosted payment page: ``action`` is the POST target, ``fields`` are the hidden inputs as given.

    The set of fields is defined by the provider and can differ between providers.
    """

    type: str = field(default="hpp_form_post", kw_only=True)

    action: str = wire_field(read_text)
    fields: Dict[str, str] = wire_field(read_text_mapping)


@dataclass
class RedirectForm(_RegistrationFormBase):
    """
    A page the customer is redirected to for the 3DS registration (``action`` is its URL).

    On the wire this form has the type ``iframe``.
    """

    type: str = field(default="iframe", kw_only=True)

    action: str = wire_field(read_text)


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
        raise InvalidArgumentError(f"'{name}' must be a valid http or https URL")


def _decimal_places(amount: Decimal) -> int:
    """How many decimal places the value really needs: ``990.000`` needs none, ``9.999`` needs three."""
    _, digits, exponent = amount.as_tuple()
    significant = "".join(map(str, digits)).rstrip("0")
    trailing_zeros = len(digits) - len(significant)
    return -int(exponent) - trailing_zeros


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
            InvalidArgumentError: If a field is invalid
        """
        email = self.customer_email
        if not isinstance(email, str) or "@" not in email or any(ch.isspace() for ch in email):
            raise InvalidArgumentError("'customer_email' must be a valid email address")

        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount <= 0:
            raise InvalidArgumentError("'amount' must be a finite Decimal greater than zero")
        if _decimal_places(self.amount) > 2:
            raise InvalidArgumentError(
                f"'amount' must have at most two decimal places, got {self.amount}: the server keeps cents, "
                "so round the amount to cents yourself first"
            )

        if not isinstance(self.currency, str) or not self.currency:
            raise InvalidArgumentError("'currency' is required")

        if not isinstance(self.billing_interval, BillingInterval):
            raise InvalidArgumentError(f"'billing_interval' must be a BillingInterval, got {self.billing_interval!r}")

        ref = self.merchant_subscription_ref
        if not isinstance(ref, str) or not 1 <= len(ref) <= MERCHANT_REF_MAX_LENGTH:
            raise InvalidArgumentError(f"'merchant_subscription_ref' must be 1 to {MERCHANT_REF_MAX_LENGTH} characters")

        _check_http_url("success_url", self.success_url)
        _check_http_url("cancel_url", self.cancel_url)
        _check_http_url("error_url", self.error_url)


@dataclass(frozen=True)
class SubscribeResponse(StrictModel):
    """
    The server response to a subscription request; names on the wire are camelCase.

    Read strictly: an answer without the subscription ID or the form, or with a malformed one, is refused here (a
    ``ValueError``, which the client reports as an ``HttpRequestError``) instead of becoming a result full of empty values.
    """

    subscription_id: UUID = wire_field(read_uuid, "subscriptionId")
    registration_form: RegistrationForm = wire_field(parse_registration_form, "registrationForm")


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
