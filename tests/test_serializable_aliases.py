"""Wire aliases and a decoder hook in Serializable, without changing existing behaviour."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar, List, Optional

import pytest

from polako.sdk._serializable import Serializable
from tests.factories import make_order_item
from tests.generators import generate_random_decimal, generate_readable_string


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


@pytest.fixture
def order_id() -> str:
    return generate_readable_string(12)


@pytest.fixture
def amount() -> Decimal:
    return generate_random_decimal(3, 2)


@pytest.fixture
def card() -> Card:
    return Card(brand=generate_readable_string(8), last4=generate_readable_string(4))


def test_from_dict_reads_alias_keys(order_id, amount):
    order = Order.from_dict({"orderId": order_id, "totalAmount": str(amount)})

    assert order.order_id == order_id
    assert order.amount == str(amount)


def test_from_dict_still_accepts_field_names(order_id, amount):
    assert Order.from_dict({"order_id": order_id, "amount": str(amount)}).order_id == order_id


def test_alias_wins_when_both_keys_are_present(amount):
    by_alias, by_name = generate_readable_string(12), generate_readable_string(12)

    assert Order.from_dict({"orderId": by_alias, "order_id": by_name, "totalAmount": str(amount)}).order_id == by_alias


def test_nested_dataclass_is_decoded_through_its_alias(order_id, amount, card):
    order = Order.from_dict(
        {"orderId": order_id, "totalAmount": str(amount), "savedCard": {"cardBrand": card.brand, "lastFour": card.last4}}
    )

    assert order.card == card


def test_fields_without_an_alias_are_unchanged(order_id, amount):
    plain = generate_readable_string(8)

    assert Order.from_dict({"orderId": order_id, "totalAmount": str(amount), "plain": plain}).plain == plain


def test_to_dict_uses_field_names_by_default(order_id, amount):
    assert Order(order_id, amount).to_dict() == {
        "order_id": order_id,
        "amount": amount,
        "card": None,
        "tags": [],
        "plain": None,
    }


def test_to_dict_by_alias_uses_wire_names_including_nested(order_id, amount, card):
    order = Order(order_id, amount, card)

    assert order.to_dict(by_alias=True) == {
        "orderId": order_id,
        "totalAmount": amount,
        "savedCard": {"cardBrand": card.brand, "lastFour": card.last4},
        "tags": [],
        "plain": None,
    }


def test_class_can_serialize_by_alias_by_default(order_id, amount):
    order = WireOrder(order_id, amount)

    assert order.to_dict() == {"orderId": order_id, "totalAmount": amount}
    assert order.to_json() == f'{{"orderId": "{order_id}", "totalAmount": "{amount}"}}'
    assert order.to_dict(by_alias=False) == {"order_id": order_id, "amount": amount}


def test_by_alias_roundtrips_through_json(order_id, amount, card):
    order = Order(order_id, amount, card)

    restored = Order.from_json(order.to_json(by_alias=True))

    assert restored.order_id == order_id and restored.card == card


def test_decoder_hook_receives_the_raw_value():
    raw = {"type": "circle", generate_readable_string(3): generate_readable_string(3)}

    assert Drawing.from_dict({"theShape": raw}).shape == ("circle", raw)


def test_decoder_hook_error_is_not_swallowed():
    unknown = generate_readable_string(8)

    with pytest.raises(UnknownKind, match=f"unknown shape type '{unknown}'"):
        Drawing.from_dict({"theShape": {"type": unknown}})


def test_decoder_is_skipped_for_a_missing_value():
    assert Drawing.from_dict({}).shape is None


def test_classes_without_metadata_behave_as_before():
    item = make_order_item()

    assert item.to_dict() == {
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "price": item.price,
        "quantity": item.quantity,
        "tax": item.tax,
    }
    assert type(item).from_dict(item.to_dict()) == item
