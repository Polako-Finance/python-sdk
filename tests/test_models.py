"""Smoke: model validation and (de)serialization."""

from decimal import Decimal

import pytest

from polako.sdk import CustomerAddress, InitCustomerInfo, OrderDetails, OrderItem, PaymentSessionDetails, SessionInfo


def make_item(**overrides):
    fields = dict(code="SKU-1", name="Ticket", description=None, price=Decimal("100.00"), quantity=2, tax="VAT")
    fields.update(overrides)
    return OrderItem(**fields)


def make_order(**overrides):
    fields = dict(currency="RSD", language="en", order_id="ORDER-1", items=[make_item()], total=Decimal("200.00"))
    fields.update(overrides)
    return OrderDetails(**fields)


def test_valid_order_passes():
    make_order().validate()


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
    with pytest.raises(ValueError, match=message):
        make_order(**overrides).validate()


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
        make_item(**overrides).validate()


def test_order_to_json_stringifies_decimal():
    assert '"total": "200.00"' in make_order().to_json()


def test_nested_roundtrip():
    address = CustomerAddress(address="Main 1", city="Belgrade", state=None, zip="11000", country="RS")
    assert CustomerAddress.from_dict(address.to_dict()) == address


@pytest.mark.parametrize(
    "overrides, message",
    [({"first_name": ""}, "first_name"), ({"last_name": ""}, "last_name"), ({"email": ""}, "email"), ({"type": "x"}, "type")],
)
def test_init_customer_validation(overrides, message):
    fields = dict(first_name="A", last_name="B", email="a@b.c", phone=None, address=None, type="person", cgid=None)
    fields.update(overrides)
    with pytest.raises(ValueError, match=message):
        InitCustomerInfo(**fields).validate()


def test_session_info_from_json():
    info = SessionInfo.from_json(
        '{"paymentSessionId": "s1", "paymentPageUrl": "https://pay", "expiresAt": "2026-01-01T00:00:00"}'
    )
    assert info.paymentSessionId == "s1"


def test_session_details_nested_parse():
    details = PaymentSessionDetails.from_dict(
        {
            "session_id": "s1",
            "language_code": "en",
            "supported_languages": ["en"],
            "payment_config": None,
            "customer": {
                "first_name": "A",
                "last_name": "B",
                "email": None,
                "phone": None,
                "address": None,
                "type": None,
                "cgid": None,
            },
            "shopping_cart": {
                "items": [
                    {
                        "id": "i1",
                        "name": "Ticket",
                        "description": None,
                        "price": 100.0,
                        "tax": 20.0,
                        "tax_schema": "VAT",
                        "quantity": 1,
                        "client_item_id": None,
                        "refunded_quantity": 0,
                    }
                ],
                "currency": "RSD",
                "total_price": 100.0,
            },
            "payment_options": [{"id": "p1", "name": "Card"}],
            "terms_url": "https://terms",
        }
    )
    assert details.shopping_cart.items[0].name == "Ticket"
    assert details.payment_options[0].id == "p1"
