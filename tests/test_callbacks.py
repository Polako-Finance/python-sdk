"""parse_payment_callback for both callback formats."""

import json
from datetime import datetime
from decimal import Decimal

import pytest

from polako.sdk import PolakoClient
from tests.factories import make_legacy_callback_body, make_refund_callback_body, make_signed_callback_body
from tests.generators import generate_api_key

FORMATS = [make_legacy_callback_body, make_signed_callback_body]


@pytest.fixture
def secret_key() -> str:
    return generate_api_key()


def test_legacy_callback_parsed(secret_key):
    body = make_legacy_callback_body(secret_key)

    callback = PolakoClient.parse_payment_callback(json.dumps(body), secret_key)

    assert callback.order_id == body["order_id"]
    assert callback.total == Decimal(body["total"])
    assert callback.currency == body["currency"]
    assert callback.tx_id == body["tx_id"]
    assert callback.tx_meta == body["tx_meta"]
    assert callback.datetime == datetime.strptime(body["datetime"], "%Y-%m-%d %H:%M")
    assert callback.success is True
    assert callback.schema_version is None


def test_legacy_failed_flag(secret_key):
    body = make_legacy_callback_body(secret_key, success=0)

    assert PolakoClient.parse_payment_callback(json.dumps(body), secret_key).success is False


def test_signed_payment_callback_parsed(secret_key):
    body = make_signed_callback_body(secret_key)

    callback = PolakoClient.parse_payment_callback(json.dumps(body), secret_key)

    assert callback.callback_type == "payment"
    assert callback.schema_version == "1.1"
    assert callback.order_id == body["order_id"]
    assert callback.session_id == body["session_id"]
    assert callback.tx_id == body["event_id"]
    assert callback.total == Decimal(body["total"])
    assert callback.success is True
    assert callback.datetime == datetime.fromisoformat(body["timestamp"])
    assert callback.merchant is not None
    assert callback.merchant.name == body["merchant"]["name"]
    assert callback.merchant.pib == body["merchant"]["pib"]
    assert callback.merchant.address == body["merchant"]["address"]


def test_signed_failed_status(secret_key):
    body = make_signed_callback_body(secret_key, status="failed")

    assert PolakoClient.parse_payment_callback(json.dumps(body), secret_key).success is False


def test_signed_refund_callback_parsed(secret_key):
    body = make_refund_callback_body(secret_key)

    callback = PolakoClient.parse_payment_callback(json.dumps(body), secret_key)

    assert callback.callback_type == "refund"
    assert callback.refunded_amount == Decimal(body["refunded_amount"])
    assert callback.refunded_items is not None
    assert callback.refunded_items[0].code == body["refunded_items"][0]["code"]
    assert callback.refunded_items[0].qty == body["refunded_items"][0]["qty"]
    assert callback.refundable == Decimal(str(body["refundable"]))


@pytest.mark.parametrize("make_body", FORMATS)
def test_bad_signature_rejected(make_body, secret_key):
    body = make_body(secret_key, signature="0" * 64)

    with pytest.raises(AssertionError):
        PolakoClient.parse_payment_callback(json.dumps(body), secret_key)


@pytest.mark.parametrize("make_body", FORMATS)
def test_signature_of_another_key_rejected(make_body, secret_key):
    body = make_body(generate_api_key())

    with pytest.raises(AssertionError):
        PolakoClient.parse_payment_callback(json.dumps(body), secret_key)


@pytest.mark.parametrize("make_body", FORMATS)
def test_signature_not_checked_without_secret(make_body, secret_key):
    body = make_body(secret_key, signature="bogus")

    assert PolakoClient.parse_payment_callback(json.dumps(body)).order_id == body["order_id"]
