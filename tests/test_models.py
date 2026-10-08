"""Model validation and (de)serialization."""

import json
from decimal import Decimal

import pytest

from polako.sdk import CustomerAddress, PaymentSessionDetails, SessionInfo
from tests.factories import (
    make_customer_address,
    make_init_customer_info,
    make_order_details,
    make_order_item,
    make_session_details_response,
    make_session_info_response,
)


def test_valid_order_passes():
    make_order_details().validate()


def test_order_total_defaults_to_the_sum_of_the_items():
    order = make_order_details()

    assert order.total == sum((item.price * item.quantity for item in order.items), Decimal("0"))


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"items": []}, "items"),
        ({"total": Decimal("0")}, "total"),
        ({"currency": "EUR"}, "currency"),
        ({"language": "de"}, "language"),
    ],
)
def test_invalid_order_rejected(overrides, message):
    order = make_order_details()
    for name, value in overrides.items():
        setattr(order, name, value)

    with pytest.raises(ValueError, match=message):
        order.validate()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"name": ""}, "name"),
        ({"price": Decimal("0")}, "price"),
        ({"quantity": 0}, "quantity"),
        ({"tax": "GST"}, "tax"),
    ],
)
def test_invalid_item_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        make_order_item(**overrides).validate()


def test_invalid_item_inside_an_order_is_rejected():
    order = make_order_details(items=[make_order_item(), make_order_item(quantity=0)])

    with pytest.raises(ValueError, match="quantity"):
        order.validate()


def test_order_to_json_stringifies_decimal():
    order = make_order_details()

    assert json.loads(order.to_json())["total"] == str(order.total)


def test_nested_roundtrip():
    address = make_customer_address()

    assert CustomerAddress.from_dict(address.to_dict()) == address


@pytest.mark.parametrize(
    "overrides, message",
    [({"first_name": ""}, "first_name"), ({"last_name": ""}, "last_name"), ({"email": ""}, "email"), ({"type": "x"}, "type")],
)
def test_init_customer_validation(overrides, message):
    with pytest.raises(ValueError, match=message):
        make_init_customer_info(**overrides).validate()


def test_valid_init_customer_passes():
    make_init_customer_info().validate()


def test_session_info_from_json():
    response = make_session_info_response()

    info = SessionInfo.from_json(json.dumps(response))

    assert info.paymentSessionId == response["paymentSessionId"]
    assert info.paymentPageUrl == response["paymentPageUrl"]
    assert info.expiresAt == response["expiresAt"]


def test_session_details_nested_parse():
    response = make_session_details_response()

    details = PaymentSessionDetails.from_dict(response)

    assert details.shopping_cart.items[0].name == response["shopping_cart"]["items"][0]["name"]
    assert details.payment_options[0].id == response["payment_options"][0]["id"]
    assert details.customer.address == CustomerAddress.from_dict(response["customer"]["address"])
    assert details.payment_config is not None
    assert details.payment_config.fields_require == response["payment_config"]["fields_require"]
