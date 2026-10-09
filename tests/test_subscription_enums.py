"""The public enums of the subscription read API, and what the package exports for managing subscriptions."""

import pytest

import polako.sdk as sdk
from polako.sdk import BillingInterval, ChargeAttemptStatus, NotFoundError, SubscriptionStatus

# The values are the server's contract: the wire names, not an SDK choice.
SUBSCRIPTION_STATUSES = {
    "PENDING_REGISTRATION": "pending_registration",
    "REGISTRATION_FAILED": "registration_failed",
    "ACTIVE": "active",
    "PAST_DUE": "past_due",
    "PAUSED": "paused",
    "CANCELLED": "cancelled",
}
CHARGE_STATUSES = {"PENDING": "pending", "SUCCEEDED": "succeeded", "FAILED": "failed"}


@pytest.mark.parametrize(
    "enum, expected", [(SubscriptionStatus, SUBSCRIPTION_STATUSES), (ChargeAttemptStatus, CHARGE_STATUSES)]
)
def test_the_members_are_exactly_the_servers_values(enum, expected):
    assert {member.name: member.value for member in enum} == expected


@pytest.mark.parametrize("enum", [SubscriptionStatus, ChargeAttemptStatus])
def test_a_member_is_its_own_string_value(enum):
    for member in enum:
        assert isinstance(member, str)
        assert member == member.value
        assert enum(member.value) is member


@pytest.mark.parametrize("enum", [SubscriptionStatus, ChargeAttemptStatus])
def test_an_unknown_value_is_not_a_member(enum):
    with pytest.raises(ValueError):
        enum("not-a-status")


def test_the_billing_interval_enum_is_unchanged():
    assert [member.value for member in BillingInterval] == ["daily", "weekly", "monthly", "quarterly", "yearly"]


@pytest.mark.parametrize("name", ["SubscriptionStatus", "ChargeAttemptStatus", "NotFoundError"])
def test_the_package_exports_it(name):
    assert name in sdk.__all__
    assert hasattr(sdk, name)


def test_not_found_is_a_request_error_with_its_own_class():
    assert issubclass(NotFoundError, sdk.HttpRequestError)
    assert NotFoundError is not sdk.HttpRequestError
