"""Checks of the arguments of the subscription read and management calls, made before any request is sent.

Every check raises ``ValueError`` with a message that names the argument. This module only validates (and normalizes
what it accepted to the form that goes on the wire); it reads nothing from the server.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Type
from uuid import UUID

SORT_FIELDS = ("created_at", "next_charge_at", "last_charged_at", "amount", "status")
SORT_ORDERS = ("asc", "desc")
LIMIT_MIN, LIMIT_MAX = 1, 100


def check_subscription_id(value: Any) -> UUID:
    """A subscription ID as a ``UUID``; a string is accepted when it is one."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError(f"'subscription_id' must be a UUID or a string holding one, got {value!r}")


def check_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not LIMIT_MIN <= value <= LIMIT_MAX:
        raise ValueError(f"'limit' must be an integer from {LIMIT_MIN} to {LIMIT_MAX}, got {value!r}")
    return value


def check_offset(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"'offset' must be an integer from 0, got {value!r}")
    return value


def check_sort_by(value: Any) -> Optional[str]:
    if value is not None and value not in SORT_FIELDS:
        raise ValueError(f"'sort_by' must be one of {', '.join(SORT_FIELDS)}, got {value!r}")
    return value  # type: ignore[no-any-return]


def check_sort_order(value: Any) -> Optional[str]:
    if value is not None and value not in SORT_ORDERS:
        raise ValueError(f"'sort_order' must be one of {', '.join(SORT_ORDERS)}, got {value!r}")
    return value  # type: ignore[no-any-return]


def check_search(value: Any) -> Optional[str]:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"'search' must be a non-blank string when given, got {value!r}")
    return value  # type: ignore[no-any-return]


def check_choices(name: str, value: Any, enum: Type[Enum]) -> Optional[List[str]]:
    """
    Values of ``enum`` as the texts that go on the wire, from one member or text, or any collection of them.

    Repeats are dropped and the order is kept. An empty collection is refused rather than read as "no filter".
    """
    if value is None:
        return None
    allowed = [member.value for member in enum]
    items = [value] if isinstance(value, (str, Enum)) else _as_list(name, value)
    if not items:
        raise ValueError(f"'{name}' must not be empty; leave it out to match any, or give one of {', '.join(allowed)}")

    chosen: List[str] = []
    for item in items:
        text = item.value if isinstance(item, enum) else item if isinstance(item, str) and not isinstance(item, Enum) else None
        if text not in allowed:
            raise ValueError(f"'{name}' has an unknown value {item!r}, allowed: {', '.join(allowed)}")
        if text not in chosen:
            chosen.append(text)
    return chosen


def _as_list(name: str, value: Any) -> List[Any]:
    try:
        return list(value)
    except TypeError:
        raise ValueError(f"'{name}' must be a value or a collection of values, got {value!r}") from None


def check_time_bound(name: str, value: Any) -> Optional[str]:
    """A day (``date``) or a timezone-aware ``datetime`` as the text the server reads: a day, or UTC to the second."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"'{name}' must carry a timezone (or be a date); a time without one is ambiguous")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    raise ValueError(f"'{name}' must be a date or a timezone-aware datetime, got {value!r}")
