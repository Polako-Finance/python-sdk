"""parse_payment_callback for both callback formats."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from polako.sdk import PolakoClient
from tests.factories import make_legacy_callback_body, make_refund_callback_body, make_signed_callback_body
from tests.generators import generate_api_key, generate_naive_datetime, generate_readable_string, generate_recent_datetime

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


@pytest.mark.parametrize("zone", ["Z", "+00:00", "+0000", "+00"])
def test_the_time_of_a_signed_callback_is_read_in_any_offset_style(secret_key, zone):
    moment = generate_recent_datetime().replace(microsecond=0)
    body = make_signed_callback_body(secret_key, timestamp=moment.replace(tzinfo=None).isoformat() + zone)

    callback = PolakoClient.parse_payment_callback(json.dumps(body), secret_key)

    assert callback.datetime.tzinfo is not None
    assert callback.datetime == moment


def test_the_time_of_a_signed_callback_may_carry_an_offset_and_a_long_fraction(secret_key):
    moment = generate_recent_datetime().replace(microsecond=468700)
    local = moment.astimezone(timezone(timedelta(hours=2)))
    body = make_signed_callback_body(secret_key, timestamp=local.replace(tzinfo=None).isoformat() + "00+02")

    callback = PolakoClient.parse_payment_callback(json.dumps(body), secret_key)

    assert callback.datetime == moment


def test_the_time_of_a_signed_callback_without_a_zone_is_utc(secret_key):
    naive = generate_naive_datetime()
    body = make_signed_callback_body(secret_key, timestamp=naive.isoformat())

    callback = PolakoClient.parse_payment_callback(json.dumps(body), secret_key)

    assert callback.datetime == naive.replace(tzinfo=timezone.utc)


def test_a_signed_callback_whose_time_is_not_a_time_is_refused(secret_key):
    body = make_signed_callback_body(secret_key, timestamp=generate_readable_string(10))

    with pytest.raises(ValueError):
        PolakoClient.parse_payment_callback(json.dumps(body), secret_key)


def test_the_time_of_a_legacy_callback_has_no_zone_as_before(secret_key):
    """The legacy format gives the minute and nothing else, so the SDK cannot say which zone it is in."""
    callback = PolakoClient.parse_payment_callback(json.dumps(make_legacy_callback_body(secret_key)), secret_key)

    assert callback.datetime.tzinfo is None
