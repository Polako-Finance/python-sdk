"""Constants for Polako Finance API."""

from enum import Enum
from typing import Literal, Set

# Currency types and supported currencies
TCurrency = Literal["RSD"]
CURRENCIES: Set[TCurrency] = {"RSD"}

# Language types and supported languages
TLanguage = Literal["sr", "en", "ru"]
LANGUAGES: Set[TLanguage] = {"sr", "en", "ru"}
DEFAULT_LANGUAGE: TLanguage = "sr"

# Tax schema types and supported schemas
TTaxSchema = Literal["VAT", "No_VAT", "Reduced_VAT"]
TAX_SCHEMAS: Set[TTaxSchema] = {"VAT", "No_VAT", "Reduced_VAT"}


class BillingInterval(str, Enum):
    """How often a subscription is charged."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class SubscriptionStatus(str, Enum):
    """Where a subscription is in its life; terminal states are `REGISTRATION_FAILED` and `CANCELLED`."""

    PENDING_REGISTRATION = "pending_registration"  # the customer has not finished the card registration (3DS)
    REGISTRATION_FAILED = "registration_failed"  # the card registration failed
    ACTIVE = "active"  # charged on schedule
    PAST_DUE = "past_due"  # the last charge failed and is being retried
    PAUSED = "paused"  # suspended, no charges
    CANCELLED = "cancelled"  # ended, no further charges


class ChargeAttemptStatus(str, Enum):
    """The outcome of one scheduled charge."""

    PENDING = "pending"  # sent to the card processor, no final answer yet
    SUCCEEDED = "succeeded"  # the money was taken
    FAILED = "failed"  # declined or errored; retries, if any, are the server's


# API base URLs
BASE_URL_PROD = "https://api.infra.polako-finance.com"
BASE_URL_TEST = "https://stg-api.infra.polako-finance.com"
