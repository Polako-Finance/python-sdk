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


# API base URLs
BASE_URL_PROD = "https://api.infra.polako-finance.com"
BASE_URL_TEST = "https://stg-api.infra.polako-finance.com"
