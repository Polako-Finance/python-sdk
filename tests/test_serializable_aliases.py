"""P1/A3: wire aliases and a decoder hook in Serializable, without changing existing behaviour."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar, List, Optional

import pytest

from polako.sdk._serializable import Serializable


@dataclass
class Card(Serializable):
    brand: str = field(metadata={"alias": "cardBrand"})
    last4: str = field(default="0000", metadata={"alias": "lastFour"})


@dataclass
class Order(Serializable):
    order_id: str = field(metadata={"alias": "orderId"})
    amount: Decimal = field(metadata={"alias": "totalAmount"})
    card: Optional[Card] = field(default=None, metadata={"alias": "savedCard"})
    tags: List[str] = field(default_factory=list)
    plain: Optional[str] = None


@dataclass
class WireOrder(Serializable):
    serialize_by_alias: ClassVar[bool] = True

    order_id: str = field(metadata={"alias": "orderId"})
    amount: Decimal = field(metadata={"alias": "totalAmount"})


class UnknownKind(ValueError):
    pass


def decode_shape(value):
    kinds = {"circle": Card, "square": Order}
    if value.get("type") not in kinds:
        raise UnknownKind(f"unknown shape type {value.get('type')!r}, known: {sorted(kinds)}")
    return value["type"], value


@dataclass
class Drawing(Serializable):
    shape: object = field(metadata={"alias": "theShape", "decode": decode_shape})


def test_from_dict_reads_alias_keys():
    order = Order.from_dict({"orderId": "A1", "totalAmount": "10.50"})

    assert order.order_id == "A1"
    assert order.amount == "10.50"


def test_from_dict_still_accepts_field_names():
    assert Order.from_dict({"order_id": "A1", "amount": "1"}).order_id == "A1"


def test_alias_wins_when_both_keys_are_present():
    assert Order.from_dict({"orderId": "alias", "order_id": "name", "totalAmount": "1"}).order_id == "alias"


def test_nested_dataclass_is_decoded_through_its_alias():
    order = Order.from_dict({"orderId": "A1", "totalAmount": "1", "savedCard": {"cardBrand": "visa", "lastFour": "4242"}})

    assert order.card == Card(brand="visa", last4="4242")


def test_fields_without_an_alias_are_unchanged():
    assert Order.from_dict({"orderId": "A1", "totalAmount": "1", "plain": "x"}).plain == "x"


def test_to_dict_uses_field_names_by_default():
    assert Order("A1", Decimal("1")).to_dict() == {
        "order_id": "A1",
        "amount": Decimal("1"),
        "card": None,
        "tags": [],
        "plain": None,
    }


def test_to_dict_by_alias_uses_wire_names_including_nested():
    order = Order("A1", Decimal("1"), Card("visa", "4242"))

    assert order.to_dict(by_alias=True) == {
        "orderId": "A1",
        "totalAmount": Decimal("1"),
        "savedCard": {"cardBrand": "visa", "lastFour": "4242"},
        "tags": [],
        "plain": None,
    }


def test_class_can_serialize_by_alias_by_default():
    order = WireOrder("A1", Decimal("10.50"))

    assert order.to_dict() == {"orderId": "A1", "totalAmount": Decimal("10.50")}
    assert order.to_json() == '{"orderId": "A1", "totalAmount": "10.50"}'
    assert order.to_dict(by_alias=False) == {"order_id": "A1", "amount": Decimal("10.50")}


def test_by_alias_roundtrips_through_json():
    order = Order("A1", Decimal("1"), Card("visa", "4242"))

    restored = Order.from_json(order.to_json(by_alias=True))

    assert restored.order_id == "A1" and restored.card == Card("visa", "4242")


def test_decoder_hook_receives_the_raw_value():
    drawing = Drawing.from_dict({"theShape": {"type": "circle", "r": 1}})

    assert drawing.shape == ("circle", {"type": "circle", "r": 1})


def test_decoder_hook_error_is_not_swallowed():
    with pytest.raises(UnknownKind, match="unknown shape type 'hexagon'"):
        Drawing.from_dict({"theShape": {"type": "hexagon"}})


def test_decoder_is_skipped_for_a_missing_value():
    assert Drawing.from_dict({}).shape is None


def test_classes_without_metadata_behave_as_before():
    from polako.sdk import OrderItem

    item = OrderItem(code="C", name="N", description=None, price=Decimal("1"), quantity=1, tax=None)

    assert item.to_dict() == {"code": "C", "name": "N", "description": None, "price": Decimal("1"), "quantity": 1, "tax": None}
    assert OrderItem.from_dict(item.to_dict()) == item
