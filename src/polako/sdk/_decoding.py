"""Reading the values of a server response: strictly where a value must be there, tolerantly where the server may grow.

A missing or malformed required value is a ``ValueError`` (the client reports it as an ``HttpRequestError``). An unknown
value of a known enum stays the raw string, and unknown fields are ignored.
"""

from dataclasses import dataclass, field, fields
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, Type
from uuid import UUID

from polako.sdk._serializable import Serializable


def read_uuid(value: Any) -> UUID:
    if not isinstance(value, str):
        raise ValueError(f"expected a UUID string, got {value!r}")
    return UUID(value)


def read_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"expected text, got {value!r}")
    return value


def read_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"expected a count, got {value!r}")
    return value


def read_money(value: Any) -> Decimal:
    """An amount sent as text or as a number; never a float's binary noise, never NaN or infinity."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"expected an amount, got {value!r}")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"expected an amount, got {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"expected a finite amount, got {value!r}")
    return amount


def read_moment(value: Any) -> datetime:
    """A time as ISO 8601 text; one without a zone is taken as UTC, so every result is timezone-aware."""
    if not isinstance(value, str):
        raise ValueError(f"expected a time as text, got {value!r}")
    moment = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def read_day(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError(f"expected a date as text, got {value!r}")
    return date.fromisoformat(value)


def read_mapping(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"expected an object, got {value!r}")
    return value


def known_or_raw(enum: Type[Enum]) -> Callable[[Any], Any]:
    """The enum member for a known value, the raw text for an unknown one (the server may add values)."""

    def decode(value: Any) -> Any:
        text = read_text(value)
        try:
            return enum(text)
        except ValueError:
            return text

    return decode


def one_of(model: Type[Serializable]) -> Callable[[Any], Any]:
    """A nested object read as ``model``."""
    return lambda value: model.from_dict(read_mapping(value))


def many_of(model: Type[Serializable]) -> Callable[[Any], Tuple[Any, ...]]:
    """A list of nested objects read as a tuple of ``model``."""

    def decode(value: Any) -> Tuple[Any, ...]:
        if not isinstance(value, list):
            raise ValueError(f"expected a list, got {value!r}")
        return tuple(model.from_dict(read_mapping(item)) for item in value)

    return decode


def wire_field(decode: Callable[[Any], Any], alias: Optional[str] = None, *, required: bool = True) -> Any:
    """A dataclass field read from the wire with ``decode``, under ``alias`` when the wire name differs."""
    metadata: Dict[str, Any] = {"decode": decode, "required": required}
    if alias:
        metadata["alias"] = alias
    return field(metadata=metadata)


@dataclass(frozen=True)
class StrictModel(Serializable):
    """A response model whose required fields must be present and not null."""

    def __post_init__(self) -> None:
        missing = [f.name for f in fields(self) if f.metadata.get("required") and getattr(self, f.name) is None]
        if missing:
            raise ValueError(f"{type(self).__name__}: missing {', '.join(missing)}")
