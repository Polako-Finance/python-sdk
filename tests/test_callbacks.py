"""Smoke: parse_payment_callback for both callback formats."""

import json
from decimal import Decimal

import pytest

from polako.sdk import PolakoClient

SECRET = "test-secret"


def sign(source: str) -> str:
    return PolakoClient._create_signature(source, SECRET)


def legacy_payload(**overrides) -> str:
    body = {
        "order_id": "ORDER-1",
        "total": "200.00",
        "currency": "RSD",
        "success": 1,
        "tx_id": "tx-1",
        "tx_meta": {},
        "datetime": "2026-05-01 12:30",
    }
    body.update(overrides)
    body.setdefault("signature", sign(f"{body['order_id']}|{body['total']}|{body['success']}"))
    return json.dumps(body)


def signed_payload(**overrides) -> str:
    body = {
        "type": "payment",
        "status": "success",
        "schema": "1.1",
        "order_id": "ORDER-1",
        "session_id": "s1",
        "event_id": "ev-1",
        "tx_meta": {},
        "timestamp": "2026-05-01T12:30:00",
        "currency": "RSD",
        "total": "200.00",
        "merchant": {"name": "Shop", "pib": "123", "address": "Main 1"},
    }
    body.update(overrides)
    amount = body.get("total") or body.get("refunded_amount")
    body.setdefault("signature", sign(f"{body['type']}|{body['status']}|{body['order_id']}|{amount}|{body['currency']}"))
    return json.dumps(body)


def test_legacy_callback_parsed():
    callback = PolakoClient.parse_payment_callback(legacy_payload(), SECRET)
    assert callback.order_id == "ORDER-1"
    assert callback.total == Decimal("200.00")
    assert callback.success is True
    assert callback.schema_version is None


def test_legacy_failed_flag():
    assert PolakoClient.parse_payment_callback(legacy_payload(success=0), SECRET).success is False


def test_signed_payment_callback_parsed():
    callback = PolakoClient.parse_payment_callback(signed_payload(), SECRET)
    assert callback.callback_type == "payment"
    assert callback.schema_version == "1.1"
    assert callback.session_id == "s1"
    assert callback.tx_id == "ev-1"
    assert callback.merchant is not None and callback.merchant.pib == "123"


def test_signed_refund_callback_parsed():
    payload = signed_payload(
        type="refund",
        total=None,
        refunded_amount="50.00",
        refunded_items=[{"code": "SKU-1", "qty": 1}],
        refundable=150.0,
    )
    callback = PolakoClient.parse_payment_callback(payload, SECRET)
    assert callback.callback_type == "refund"
    assert callback.refunded_amount == Decimal("50.00")
    assert callback.refunded_items is not None and callback.refunded_items[0].qty == 1
    assert callback.refundable == Decimal("150.0")


@pytest.mark.parametrize("make_payload", [legacy_payload, signed_payload])
def test_bad_signature_rejected(make_payload):
    with pytest.raises(AssertionError):
        PolakoClient.parse_payment_callback(make_payload(signature="0" * 64), SECRET)


@pytest.mark.parametrize("make_payload", [legacy_payload, signed_payload])
def test_signature_not_checked_without_secret(make_payload):
    assert PolakoClient.parse_payment_callback(make_payload(signature="bogus")).order_id == "ORDER-1"
