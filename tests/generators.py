"""Random data for tests.

Two runs never share values, and a test names a literal only when that literal is what it checks.
"""

import random
import string
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


def generate_random_digit_string(length: int) -> str:
    return "".join(random.choices(string.digits, k=length))


def generate_random_decimal(digits_before: int, digits_after: int) -> Decimal:
    if digits_before <= 0 or digits_after < 0:
        raise ValueError("digits_before must be > 0, digits_after must be >= 0")

    integer_part = random.randint(10 ** (digits_before - 1), 10**digits_before - 1)
    if digits_after == 0:
        return Decimal(str(integer_part))

    fractional_part = "".join(random.choices(string.digits, k=digits_after))
    return Decimal(f"{integer_part}.{fractional_part}")


def generate_readable_string(length: int) -> str:
    """Letters and digits, starting with a letter."""
    if length <= 0:
        raise ValueError("Length must be a positive integer")

    first = random.choice(string.ascii_letters)
    rest = "".join(random.choices(string.ascii_letters + string.digits, k=length - 1))
    return first + rest


def generate_random_email() -> str:
    username = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(5, 10)))
    return f"{username}@example.com"


def generate_random_host() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=random.randint(5, 10))) + ".example.com"


def generate_random_url(path_length: int = 8) -> str:
    return f"https://{generate_random_host()}/{generate_readable_string(path_length)}"


def generate_api_key() -> str:
    """A platform API key: 32 hex characters."""
    return "".join(random.choices("0123456789abcdef", k=32))


def generate_recent_datetime(days_ago: int = 0, hours_ago: int = 0) -> datetime:
    """A timezone-aware instant that many days or hours before now."""
    return datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)


def generate_recent_date(days_ago_max: int = 60) -> date:
    """A day within the last `days_ago_max` days, counted from today (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=random.randint(0, days_ago_max))).date()


def generate_aware_datetime() -> datetime:
    """A recent instant with random microseconds, written in a random UTC offset (not always UTC)."""
    zone = timezone(timedelta(hours=random.randint(-11, 12)))
    instant = generate_recent_datetime(days_ago=random.randint(0, 30), hours_ago=random.randint(0, 23))
    return instant.replace(microsecond=random.randint(1, 999_999)).astimezone(zone)


def generate_naive_datetime() -> datetime:
    """A recent local time with no zone attached."""
    return generate_recent_datetime(days_ago=random.randint(0, 30)).replace(tzinfo=None)
