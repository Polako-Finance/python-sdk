"""The checks of the arguments of the read and management calls."""

import random
from datetime import timezone
from uuid import UUID, uuid4

import pytest

from polako.sdk import BillingInterval, SubscriptionStatus
from polako.sdk._validation import (
    LIMIT_MAX,
    LIMIT_MIN,
    SORT_FIELDS,
    SORT_ORDERS,
    check_choices,
    check_limit,
    check_offset,
    check_search,
    check_sort_by,
    check_sort_order,
    check_subscription_id,
    check_time_bound,
)
from tests.generators import (
    generate_aware_datetime,
    generate_naive_datetime,
    generate_readable_string,
    generate_recent_date,
    generate_recent_datetime,
)

# ---------------------------------------------------------------------------
# subscription id
# ---------------------------------------------------------------------------


def test_a_uuid_is_accepted_as_it_is():
    value = uuid4()

    assert check_subscription_id(value) == value


def test_a_uuid_string_becomes_a_uuid_in_any_case_and_form():
    value = uuid4()

    for text in (str(value), str(value).upper(), value.hex):
        assert check_subscription_id(text) == value and isinstance(check_subscription_id(text), UUID)


@pytest.mark.parametrize("bad", [None, "", " ", "not-a-uuid", 12345, 1.5, b"x" * 16, [uuid4()], True])
def test_anything_else_is_not_a_subscription_id(bad):
    with pytest.raises(ValueError, match="subscription_id"):
        check_subscription_id(bad)


# ---------------------------------------------------------------------------
# paging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [LIMIT_MIN, LIMIT_MAX, random.randint(LIMIT_MIN, LIMIT_MAX)])
def test_a_limit_in_range_is_accepted(value):
    assert check_limit(value) == value


@pytest.mark.parametrize("bad", [0, -1, LIMIT_MAX + 1, 1.5, True, "10", None])
def test_a_limit_out_of_range_or_not_a_number_is_refused(bad):
    with pytest.raises(ValueError, match="limit"):
        check_limit(bad)


@pytest.mark.parametrize("value", [0, 1, random.randint(2, 10_000)])
def test_an_offset_from_zero_is_accepted(value):
    assert check_offset(value) == value


@pytest.mark.parametrize("bad", [-1, 1.5, True, "0", None])
def test_a_negative_or_non_integer_offset_is_refused(bad):
    with pytest.raises(ValueError, match="offset"):
        check_offset(bad)


# ---------------------------------------------------------------------------
# sorting and search
# ---------------------------------------------------------------------------


def test_sorting_is_optional_and_limited_to_the_servers_fields_and_orders():
    assert check_sort_by(None) is None and check_sort_order(None) is None
    for name in SORT_FIELDS:
        assert check_sort_by(name) == name
    for order in SORT_ORDERS:
        assert check_sort_order(order) == order


@pytest.mark.parametrize("bad", ["", "id", "CREATED_AT", generate_readable_string(8), 5])
def test_an_unknown_sort_field_is_refused(bad):
    with pytest.raises(ValueError, match="sort_by"):
        check_sort_by(bad)


@pytest.mark.parametrize("bad", ["", "ASC", "up", 1])
def test_an_unknown_sort_order_is_refused(bad):
    with pytest.raises(ValueError, match="sort_order"):
        check_sort_order(bad)


def test_search_is_optional_and_not_blank():
    text = generate_readable_string(6)

    assert check_search(None) is None
    assert check_search(text) == text


@pytest.mark.parametrize("bad", ["", "   ", "\t\n", 5, b"x"])
def test_a_blank_or_non_text_search_is_refused(bad):
    with pytest.raises(ValueError, match="search"):
        check_search(bad)


# ---------------------------------------------------------------------------
# filters by status and by interval
# ---------------------------------------------------------------------------


def test_no_filter_is_none():
    assert check_choices("status", None, SubscriptionStatus) is None


def test_one_member_or_one_text_is_one_choice():
    assert check_choices("status", SubscriptionStatus.PAUSED, SubscriptionStatus) == ["paused"]
    assert check_choices("status", "paused", SubscriptionStatus) == ["paused"]
    assert check_choices("billing_interval", BillingInterval.WEEKLY, BillingInterval) == ["weekly"]


def test_several_choices_keep_their_order_and_drop_repeats():
    chosen = [SubscriptionStatus.ACTIVE, "paused", SubscriptionStatus.ACTIVE, "past_due"]

    assert check_choices("status", chosen, SubscriptionStatus) == ["active", "paused", "past_due"]


@pytest.mark.parametrize("container", [list, tuple, set, frozenset, iter])
def test_any_collection_of_choices_is_accepted(container):
    result = check_choices("status", container([SubscriptionStatus.ACTIVE]), SubscriptionStatus)

    assert result == ["active"]


@pytest.mark.parametrize("bad", ["nope", "ACTIVE", ["active", "nope"], [5], 5, [None], []])
def test_an_unknown_wrong_typed_or_empty_choice_is_refused(bad):
    with pytest.raises(ValueError, match="status"):
        check_choices("status", bad, SubscriptionStatus)


def test_the_message_lists_the_allowed_values():
    with pytest.raises(ValueError) as caught:
        check_choices("billing_interval", "hourly", BillingInterval)

    assert all(member.value in str(caught.value) for member in BillingInterval)


# ---------------------------------------------------------------------------
# creation time bounds
# ---------------------------------------------------------------------------


def test_no_bound_is_none():
    assert check_time_bound("created_from", None) is None


def test_a_date_is_sent_as_a_day():
    day = generate_recent_date()

    assert check_time_bound("created_from", day) == day.isoformat()


def test_an_aware_time_is_sent_in_utc_with_a_z_and_whole_seconds():
    moment = generate_aware_datetime()
    expected = moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    assert check_time_bound("created_to", moment) == expected


def test_the_same_instant_in_any_zone_gives_the_same_text():
    moment = generate_aware_datetime()
    in_utc = moment.astimezone(timezone.utc)

    assert check_time_bound("created_from", moment) == check_time_bound("created_from", in_utc)


@pytest.mark.parametrize(
    "bad",
    [
        generate_naive_datetime(),
        generate_recent_date().isoformat(),
        int(generate_recent_datetime().timestamp()),
        generate_recent_datetime().timestamp(),
        True,
        generate_recent_date().isoformat().encode(),
    ],
    ids=["naive-datetime", "text", "int", "float", "bool", "bytes"],
)
def test_a_naive_time_or_a_non_time_is_refused(bad):
    with pytest.raises(ValueError, match="created_from"):
        check_time_bound("created_from", bad)
