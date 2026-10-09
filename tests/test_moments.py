"""How the SDK reads a time that the server sends: one reader, the same on every supported Python."""

import random
from datetime import datetime, timedelta, timezone

import pytest

from polako.sdk import parse_subscription_webhook
from polako.sdk._decoding import parse_moment, read_moment
from tests.factories import generate_api_key, make_charge_succeeded_payload, make_signed_webhook
from tests.generators import generate_aware_datetime, generate_naive_datetime


def offset_text(offset: timedelta, style: str) -> str:
    """An offset written in one of the usual ways."""
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return {
        "colon": f"{sign}{hours:02d}:{rest:02d}",
        "plain": f"{sign}{hours:02d}{rest:02d}",
        "hours": f"{sign}{hours:02d}" if rest == 0 else f"{sign}{hours:02d}:{rest:02d}",
    }[style]


@pytest.mark.parametrize("style", ["colon", "plain", "hours"])
def test_a_numeric_offset_in_any_style_keeps_the_instant(style):
    zone = timezone(timedelta(hours=random.randint(-11, 12)))
    moment = generate_aware_datetime().astimezone(zone)
    text = moment.replace(tzinfo=None).isoformat() + offset_text(zone.utcoffset(None), style)

    read = parse_moment(text)

    assert read.tzinfo is not None and read == moment


def test_a_trailing_z_is_utc():
    moment = generate_aware_datetime().astimezone(timezone.utc)

    assert parse_moment(moment.replace(tzinfo=None).isoformat() + "Z") == moment


@pytest.mark.parametrize("digits", [1, 2, 3, 4, 5, 6, 7, 9])
@pytest.mark.parametrize("suffix", ["Z", "+00:00", "+00", ""])
def test_any_number_of_fraction_digits_is_read_to_the_microsecond(digits, suffix):
    fraction = "".join(random.choice("123456789") for _ in range(digits))
    expected_micro = int((fraction + "000000")[:6])

    read = parse_moment(f"2026-03-05T10:20:30.{fraction}{suffix}")

    assert read.microsecond == expected_micro
    assert read.replace(microsecond=0) == datetime(2026, 3, 5, 10, 20, 30, tzinfo=timezone.utc)


def test_a_time_with_no_fraction_is_whole_seconds():
    assert parse_moment("2026-03-05T10:20:30Z").microsecond == 0


def test_a_time_without_a_zone_is_utc_and_so_is_always_aware():
    naive = generate_naive_datetime()

    read = parse_moment(naive.isoformat())

    assert read.tzinfo is not None and read.utcoffset() == timedelta(0)
    assert read == naive.replace(tzinfo=timezone.utc)


def test_a_space_may_separate_the_day_from_the_time():
    assert parse_moment("2026-03-05 10:20:30Z") == datetime(2026, 3, 5, 10, 20, 30, tzinfo=timezone.utc)


def test_a_bare_day_is_midnight_utc():
    assert parse_moment("2026-03-05") == datetime(2026, 3, 5, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "yesterday",
        "2026-13-01T00:00:00Z",
        "2026-02-30T00:00:00Z",
        "2026-03-05T25:00:00Z",
        "2026-03-05T10:61:00Z",
        "2026-03-05T10:20:30.Z",
        "2026-03-05T10:20:30Zjunk",
        "2026-03-05T10:20:30+25:00",
        "T10:20:30Z",
        "10:20:30",
        "2026-03-05T10:20:30 +02:00 extra",
    ],
)
def test_what_is_not_a_time_is_refused(bad):
    with pytest.raises(ValueError):
        parse_moment(bad)


def test_the_reader_of_a_response_field_is_the_same_reader():
    text = "2026-03-05T10:20:30.4687+00"

    assert read_moment(text) == parse_moment(text)


@pytest.mark.parametrize(
    "not_text", [None, 1700000000, 1.5, b"2026-03-05T10:20:30Z", ["2026-03-05"], generate_naive_datetime()]
)
def test_a_response_field_that_is_not_text_is_refused(not_text):
    with pytest.raises(ValueError):
        read_moment(not_text)


def test_the_time_of_a_charge_in_a_webhook_is_aware_even_without_a_zone():
    key = generate_api_key()
    naive = generate_naive_datetime()
    body, signature = make_signed_webhook(make_charge_succeeded_payload(charged_at=naive.isoformat()), key)

    event = parse_subscription_webhook(body, signature, key)

    assert event.charged_at.tzinfo is not None
    assert event.charged_at == naive.replace(tzinfo=timezone.utc)


def test_the_time_of_a_charge_in_a_webhook_is_read_with_an_unusual_offset_and_fraction():
    key = generate_api_key()
    body, signature = make_signed_webhook(make_charge_succeeded_payload(charged_at="2026-03-05T12:20:30.4687+02"), key)

    event = parse_subscription_webhook(body, signature, key)

    assert event.charged_at == datetime(2026, 3, 5, 10, 20, 30, 468700, tzinfo=timezone.utc)
