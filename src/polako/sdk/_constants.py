"""Constants for Polako Finance API."""

from typing import Literal, Set

# Currency types and supported currencies
TCurrency = Literal["RSD"]
CURRENCIES: Set[TCurrency] = {"RSD"}

# Language types and supported languages
TLanguage = Literal["sr", "en", "ru"]
LANGUAGES: Set[TLanguage] = {"sr", "en", "ru"}

# Tax schema types and supported schemas
TTaxSchema = Literal["VAT", "No_VAT", "Reduced_VAT"]
TAX_SCHEMAS: Set[TTaxSchema] = {"VAT", "No_VAT", "Reduced_VAT"}

# API base URLs
BASE_URL_PROD = "https://backend.polako-finance.com"
BASE_URL_TEST = "https://stg-backend.polako-finance.com"
