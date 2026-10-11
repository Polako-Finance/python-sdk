"""What a list request asks of the server: the query parameters built from the caller's arguments."""

import random
from dataclasses import FrozenInstanceError
from datetime import timezone

import pytest

from polako.sdk import BillingInterval, SubscriptionStatus
from polako.sdk._subscription_list import SubscriptionListQuery
from tests.generators import generate_aware_datetime, generate_naive_datetime, generate_readable_string, generate_recent_date


def build(**arguments) -> SubscriptionListQuery:
    """The query for arguments as the client passes them (the defaults of `list_subscriptions` for the rest)."""
    defaults = dict(
        status=None,
        billing_interval=None,
        search=None,
        created_from=None,
        created_to=None,
        sort_by=None,
        sort_order=None,
        limit=10,
        offset=0,
    )
    defaults.update(arguments)
    return SubscriptionListQuery.from_arguments(**defaults)


def test_without_filters_only_the_page_is_asked_for():
    assert build().to_params() == {"limit": 10, "offset": 0}


def test_the_page_is_sent_as_given():
    limit, offset = random.randint(1, 100), random.randint(0, 5000)

    assert build(limit=limit, offset=offset).to_params() == {"limit": limit, "offset": offset}


def test_every_filter_goes_under_the_servers_name():
    text = generate_readable_string(7)
    start = generate_recent_date()
    end = generate_aware_datetime()
    end_wire = end.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    params = build(
        status=[SubscriptionStatus.ACTIVE, "paused"],
        billing_interval=BillingInterval.MONTHLY,
        search=text,
        created_from=start,
        created_to=end,
        sort_by="amount",
        sort_order="desc",
        limit=25,
        offset=50,
    ).to_params()

    assert params == {
        "status": ["active", "paused"],
        "billing_interval": ["monthly"],
        "filter": text,
        "date_from": start.isoformat(),
        "date_to": end_wire,
        "sort_by": "amount",
        "sort_order": "desc",
        "limit": 25,
        "offset": 50,
    }


@pytest.mark.parametrize(
    "name, wire",
    [
        ("status", "status"),
        ("billing_interval", "billing_interval"),
        ("search", "filter"),
        ("created_from", "date_from"),
        ("created_to", "date_to"),
        ("sort_by", "sort_by"),
        ("sort_order", "sort_order"),
    ],
)
def test_a_filter_that_is_not_given_is_not_sent(name, wire):
    given = {
        "status": "active",
        "billing_interval": "daily",
        "search": generate_readable_string(5),
        "created_from": generate_recent_date(),
        "created_to": generate_recent_date(),
        "sort_by": "status",
        "sort_order": "asc",
    }
    del given[name]

    assert wire not in build(**given).to_params()


def test_the_arguments_are_checked_when_the_query_is_built():
    with pytest.raises(ValueError, match="limit"):
        build(limit=0)
    with pytest.raises(ValueError, match="status"):
        build(status="nope")
    with pytest.raises(ValueError, match="created_to"):
        build(created_to=generate_naive_datetime())
    with pytest.raises(ValueError, match="sort_by"):
        build(sort_by="id")


def test_a_query_cannot_be_changed():
    query = build()

    with pytest.raises(FrozenInstanceError):
        query.limit = 5  # type: ignore[misc]
