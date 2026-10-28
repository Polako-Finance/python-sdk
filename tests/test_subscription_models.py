"""Subscription models, enums and registration form parsing."""

import json
from dataclasses import asdict, fields
from decimal import Decimal
from uuid import UUID

import pytest

import polako.sdk as sdk
from polako.sdk import BillingInterval, FormPost, HppFormPost, RedirectForm, UnknownRegistrationFormError
from polako.sdk._subscription import _FORMS_BY_TYPE, SubscribeResponse, parse_registration_form
from tests.factories import (
    FORM_RESPONSE_BUILDERS,
    make_form_post_response,
    make_hpp_form_response,
    make_redirect_form_response,
    make_subscribe_args,
    make_subscribe_request,
    make_subscribe_response,
)
from tests.generators import generate_random_decimal, generate_random_int, generate_readable_string

FORM_POST_FIELDS = [
    ("action", "action"),
    ("version", "version"),
    ("merchant_id", "merchantId"),
    ("terminal_id", "terminalId"),
    ("total_amount", "totalAmount"),
    ("currency", "currency"),
    ("locale", "locale"),
    ("purchase_time", "purchaseTime"),
    ("order_id", "orderId"),
    ("signature", "signature"),
]


def test_billing_interval_matches_the_server_values():
    assert [i.value for i in BillingInterval] == ["daily", "weekly", "monthly", "quarterly", "yearly"]
    assert BillingInterval("monthly") is BillingInterval.MONTHLY


def test_form_post_is_parsed_with_python_names():
    raw = make_form_post_response()

    form = parse_registration_form(raw)

    assert isinstance(form, FormPost)
    assert form.type == "form_post"
    for attribute, wire_name in FORM_POST_FIELDS:
        assert getattr(form, attribute) == raw[wire_name], attribute


def test_hpp_form_post_keeps_the_provider_defined_fields():
    raw = make_hpp_form_response()

    form = parse_registration_form(raw)

    assert isinstance(form, HppFormPost)
    assert form.type == "hpp_form_post"
    assert form.action == raw["action"]
    assert form.fields == raw["fields"]


def test_wire_type_iframe_is_a_redirect_form():
    raw = make_redirect_form_response()

    form = parse_registration_form(raw)

    assert isinstance(form, RedirectForm)
    assert form.type == "iframe"
    assert form.action == raw["action"]


FORM_KINDS = pytest.mark.parametrize("make_raw", list(FORM_RESPONSE_BUILDERS.values()), ids=list(FORM_RESPONSE_BUILDERS))


def test_the_tests_build_every_kind_of_form_the_sdk_reads():
    assert set(FORM_RESPONSE_BUILDERS) == set(_FORMS_BY_TYPE)


# A page that sends the customer on with the JavaScript SDK takes the form as the gateway sent it, type included.
@FORM_KINDS
def test_a_form_turns_back_into_what_the_gateway_sent(make_raw):
    raw = make_raw()

    form = parse_registration_form(raw)

    assert form.to_dict() == raw
    assert json.loads(form.to_json()) == raw
    assert next(iter(form.to_dict())) == "type"


@FORM_KINDS
def test_a_form_with_python_names_keeps_its_type_first(make_raw):
    form = parse_registration_form(make_raw())

    as_python = form.to_dict(by_alias=False)

    assert as_python == {"type": form.type, **{f.name: getattr(form, f.name) for f in fields(form) if f.name != "type"}}
    assert next(iter(as_python)) == "type"


# Serializers that walk the fields of a dataclass (dataclasses.asdict, FastAPI's encoder) keep the type too.
@FORM_KINDS
def test_a_form_carries_its_type_as_a_field(make_raw):
    raw = make_raw()

    form = parse_registration_form(raw)

    assert asdict(form)["type"] == raw["type"]


@FORM_KINDS
def test_a_form_is_made_again_from_its_python_names(make_raw):
    form = parse_registration_form(make_raw())

    assert type(form)(**form.to_dict(by_alias=False)) == form


# A form read back as another kind is refused, not turned into a form of empty or wrong values.
@pytest.mark.parametrize(
    "model, make_raw",
    [
        (RedirectForm, make_form_post_response),
        (FormPost, make_hpp_form_response),
        (HppFormPost, make_redirect_form_response),
    ],
    ids=["form_post as iframe", "hpp_form_post as form_post", "iframe as hpp_form_post"],
)
def test_a_form_of_another_kind_is_refused(model, make_raw):
    with pytest.raises(ValueError, match="type"):
        model.from_dict(make_raw())


# A dict without a type (what 0.2.2's to_dict() gave, in Python names) is read as the model's own kind.
@FORM_KINDS
def test_a_form_dict_without_a_type_is_read_as_the_models_own_kind(make_raw):
    form = parse_registration_form(make_raw())
    saved = {name: value for name, value in form.to_dict(by_alias=False).items() if name != "type"}

    assert type(form).from_dict(saved) == form


# Without a type, a dict of another kind is still refused: its fields are not the model's.
@pytest.mark.parametrize(
    "model, make_raw",
    [
        (RedirectForm, make_form_post_response),
        (RedirectForm, make_hpp_form_response),
        (FormPost, make_hpp_form_response),
        (HppFormPost, make_form_post_response),
    ],
    ids=["form_post as iframe", "hpp_form_post as iframe", "hpp_form_post as form_post", "form_post as hpp_form_post"],
)
def test_a_form_of_another_kind_without_a_type_is_refused(model, make_raw):
    form = parse_registration_form(make_raw())
    saved = {name: value for name, value in form.to_dict(by_alias=False).items() if name != "type"}

    with pytest.raises(ValueError):
        model.from_dict(saved)


# The gateway's schema allows an hpp_form_post without fields; the subscription exists by then, so the form is kept.
def test_an_hpp_form_without_fields_from_the_gateway_is_a_form():
    raw = make_hpp_form_response(fields={})

    form = parse_registration_form(raw)

    assert isinstance(form, HppFormPost) and form.fields == {}
    assert SubscribeResponse.from_json(json.dumps(make_subscribe_response(raw))).registration_form == form


@pytest.mark.parametrize("model", [FormPost, HppFormPost, RedirectForm])
def test_a_form_is_made_only_with_its_own_type(model):
    other = next(kind for kind in _FORMS_BY_TYPE if kind != model.type)
    raw = FORM_RESPONSE_BUILDERS[model.type]()

    with pytest.raises(ValueError, match="type"):
        model.from_dict({**raw, "type": other})


# The dict handed to a page is a copy: changing it (to hide a value before logging it) leaves the form as it was.
def test_the_fields_of_an_hpp_form_dict_are_a_copy():
    raw = make_hpp_form_response()
    sent = dict(raw["fields"])
    form = parse_registration_form(raw)

    handed_out = form.to_dict()
    handed_out["fields"][next(iter(sent))] = generate_readable_string(8)
    handed_out["fields"].clear()

    assert form.fields == sent
    assert form.to_dict()["fields"] == sent


# Half a form from the gateway is refused when the subscription is created, before any page gets nulls from it.
HALF_FORMS = {
    "form_post without a field": lambda: _without(make_form_post_response(), "signature"),
    "form_post with a null field": lambda: make_form_post_response(orderId=None),
    "form_post with a number": lambda: make_form_post_response(totalAmount=generate_random_int()),
    "hpp_form_post without fields": lambda: _without(make_hpp_form_response(), "fields"),
    "hpp_form_post with fields that are not an object": lambda: make_hpp_form_response(fields=[generate_readable_string(5)]),
    "hpp_form_post with a value that is not text": lambda: make_hpp_form_response(
        fields={generate_readable_string(5): generate_random_int()}
    ),
    "iframe without an action": lambda: _without(make_redirect_form_response(), "action"),
    "iframe with a null action": lambda: make_redirect_form_response(action=None),
}


def _without(raw, name):
    return {key: value for key, value in raw.items() if key != name}


@pytest.mark.parametrize("make_half", list(HALF_FORMS.values()), ids=list(HALF_FORMS))
def test_half_a_form_is_refused(make_half):
    with pytest.raises(ValueError):
        parse_registration_form(make_half())

    with pytest.raises(ValueError):
        SubscribeResponse.from_json(json.dumps(make_subscribe_response(make_half())))


def test_unknown_form_type_names_the_type_and_the_known_ones():
    unknown = "qr_" + generate_readable_string(5)

    with pytest.raises(UnknownRegistrationFormError) as exc:
        parse_registration_form(make_redirect_form_response(type=unknown))

    message = str(exc.value)
    assert unknown in message
    for known in ("form_post", "hpp_form_post", "iframe"):
        assert known in message


@pytest.mark.parametrize("raw", [{"action": "https://x"}, {"type": None, "action": "https://x"}, {}])
def test_form_without_a_type_is_rejected(raw):
    with pytest.raises(UnknownRegistrationFormError):
        parse_registration_form(raw)


def test_unknown_form_error_is_a_value_error():
    assert issubclass(UnknownRegistrationFormError, ValueError)


def test_response_is_parsed_from_camel_case_json():
    raw = make_subscribe_response(make_hpp_form_response())

    response = SubscribeResponse.from_json(json.dumps(raw))

    assert response.subscription_id == UUID(raw["subscriptionId"])
    assert isinstance(response.registration_form, HppFormPost)


def test_response_with_an_unknown_form_raises_the_specific_error():
    raw = make_subscribe_response(make_redirect_form_response(type="qr_" + generate_readable_string(5)))

    with pytest.raises(UnknownRegistrationFormError):
        SubscribeResponse.from_json(json.dumps(raw))


BROKEN_ANSWERS = {
    "nothing": lambda raw: {},
    "no id": lambda raw: {"registrationForm": raw["registrationForm"]},
    "null id": lambda raw: {**raw, "subscriptionId": None},
    "id that is not a UUID": lambda raw: {**raw, "subscriptionId": generate_readable_string(12)},
    "id that is a number": lambda raw: {**raw, "subscriptionId": 12345},
    "no form": lambda raw: {"subscriptionId": raw["subscriptionId"]},
    "null form": lambda raw: {**raw, "registrationForm": None},
    "form that is text": lambda raw: {**raw, "registrationForm": generate_readable_string(8)},
}


@pytest.mark.parametrize("make_broken", list(BROKEN_ANSWERS.values()), ids=list(BROKEN_ANSWERS))
def test_half_an_answer_is_refused_not_turned_into_empty_values(make_broken):
    broken = make_broken(make_subscribe_response())

    with pytest.raises(ValueError):
        SubscribeResponse.from_json(json.dumps(broken))


def test_request_is_sent_in_camel_case_with_a_string_amount():
    args = make_subscribe_args()

    body = json.loads(make_subscribe_request(**args).to_json())

    assert body == {
        "customerEmail": args["customer_email"],
        "amount": str(args["amount"]),
        "currency": args["currency"],
        "billingInterval": args["billing_interval"].value,
        "merchantSubscriptionRef": args["merchant_subscription_ref"],
        "successUrl": args["success_url"],
        "cancelUrl": args["cancel_url"],
        "errorUrl": args["error_url"],
    }


def test_request_body_has_no_snake_case_keys():
    assert not [key for key in json.loads(make_subscribe_request().to_json()) if "_" in key]


def test_valid_request_passes_validation():
    make_subscribe_request().validate()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"customer_email": ""}, "customer_email"),
        ({"customer_email": "no-at-sign"}, "customer_email"),
        ({"amount": Decimal("0")}, "amount"),
        ({"amount": Decimal("-5")}, "amount"),
        ({"amount": Decimal("NaN")}, "amount"),
        ({"amount": Decimal("Infinity")}, "amount"),
        ({"amount": 990.5}, "amount"),
        ({"amount": Decimal("9.999")}, "decimal places"),
        ({"amount": Decimal("0.001")}, "decimal places"),
        ({"amount": Decimal("1E-3")}, "decimal places"),
        ({"amount": Decimal("9.9990")}, "decimal places"),
        ({"amount": Decimal("0.0010")}, "decimal places"),
        ({"amount": generate_random_decimal(3, 2) + Decimal("0.005")}, "decimal places"),
        ({"currency": ""}, "currency"),
        ({"merchant_subscription_ref": ""}, "merchant_subscription_ref"),
        ({"merchant_subscription_ref": "x" * 129}, "merchant_subscription_ref"),
        ({"success_url": "ftp://shop.example.com/ok"}, "success_url"),
        ({"cancel_url": "javascript:alert(1)"}, "cancel_url"),
        ({"error_url": "https://"}, "error_url"),
        ({"error_url": ""}, "error_url"),
    ],
)
def test_invalid_request_is_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        make_subscribe_request(**overrides).validate()


def test_the_error_for_too_many_decimal_places_says_to_round_first_and_names_the_amount():
    amount = generate_random_decimal(3, 2) + Decimal("0.005")

    with pytest.raises(ValueError) as exc:
        make_subscribe_request(amount=amount).validate()

    message = str(exc.value)
    assert "round" in message
    assert str(amount) in message


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("990"),
        Decimal("990.0"),
        Decimal("990.00"),
        Decimal("990.000"),
        Decimal("1E+3"),
        Decimal("0.01"),
        generate_random_decimal(3, 2),
        generate_random_decimal(1, 1),
    ],
)
def test_an_amount_with_at_most_two_decimal_places_is_accepted(amount):
    make_subscribe_request(amount=amount).validate()


def test_reference_of_128_characters_is_accepted():
    make_subscribe_request(merchant_subscription_ref=generate_readable_string(128)).validate()


def test_public_names_are_exported():
    for name in (
        "BillingInterval",
        "FormPost",
        "HppFormPost",
        "RedirectForm",
        "SubscriptionCreated",
        "UnknownRegistrationFormError",
        "ConfigurationError",
    ):
        assert name in sdk.__all__, name
