from typing import Literal, Set

TCurrency = Literal["RSD"]
CURRENCIES: Set[TCurrency] = {"RSD"}

TLanguage = Literal["sr", "en", "ru"]
LANGUAGES: Set[TLanguage] = {"sr", "en", "ru"}

TTaxSchema = Literal["VAT", "No_VAT", "Reduced_VAT"]
TAX_SCHEMAS: Set[TTaxSchema] = {"VAT", "No_VAT", "Reduced_VAT"}

BASE_URL_PROD = "https://backend.polako-finance.com"
BASE_URL_TEST = "https://stg-backend.polako-finance.com"
