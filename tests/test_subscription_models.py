"""Subscription models, enums and registration form parsing."""

import json
from decimal import Decimal
from uuid import UUID

import pytest

import polako.sdk as sdk
from polako.sdk import BillingInterval, FormPost, HppFormPost, RedirectForm, UnknownRegistrationFormError
from polako.sdk._subscription import SubscribeResponse, parse_registration_form
from tests.factories import (
    make_form_post_response,
    make_hpp_form_response,
    make_redirect_form_response,
    make_subscribe_args,
    make_subscribe_request,
    make_subscribe_response,
)
from tests.generators import generate_readable_string

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
