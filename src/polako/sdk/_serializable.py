"""Base serializable class for data models."""

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any, Dict, Type, TypeVar, Union, cast, get_args, get_origin
from uuid import UUID

T = TypeVar("T", bound="Serializable")


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles UUID and Decimal types."""

    def default(self, obj):
        """Convert UUID and Decimal to JSON-serializable types."""
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class Serializable:
    """
    Base class for serializable dataclasses.

    Provides methods to convert between dataclass instances, dictionaries, and JSON strings.
    Supports nested dataclasses and lists of dataclasses.
    """

    @classmethod
    def from_dict(cls: Type[T], data: dict) -> T:
        """
        Create an instance from a dictionary.

        Args:
            data: Dictionary containing field values

        Returns:
            Instance of the class with values from the dictionary
        """
        init_args: Dict[str, Any] = {}
        for f in fields(cls):  # type: ignore[arg-type]
            field_type = f.type
            value = data.get(f.name)

            if value is None:
                init_args[f.name] = None
                continue

            origin = get_origin(field_type)
            args = get_args(field_type)

            if origin is list and args and is_dataclass(args[0]):
                # Type narrowing: args[0] is a dataclass that should be Serializable
                item_cls = cast(Serializable, args[0])
                init_args[f.name] = [item_cls.from_dict(v) for v in value]
            elif is_dataclass(field_type) and isinstance(value, dict):
                # Type narrowing: field_type is a dataclass that should be Serializable
                nested_cls = cast(Serializable, field_type)
                init_args[f.name] = nested_cls.from_dict(value)
            elif origin is Union:
                # Handle Optional[SomeDataclass] (Union[SomeDataclass, None])
                resolved = False
                for arg in args:
                    if is_dataclass(arg) and isinstance(value, dict):
                        init_args[f.name] = cast(Serializable, arg).from_dict(value)
                        resolved = True
                        break
                if not resolved:
                    init_args[f.name] = value
            else:
                init_args[f.name] = value

        return cls(**init_args)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert instance to a dictionary.

        Returns:
            Dictionary representation of the instance
        """
        result: Dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            if isinstance(value, list):
                result[f.name] = [cast(Serializable, v).to_dict() if is_dataclass(v) else v for v in value]
            elif is_dataclass(value):
                result[f.name] = cast(Serializable, value).to_dict()
            else:
                result[f.name] = value
        return result

    def to_json(self) -> str:
        """
        Convert instance to a JSON string.

        Returns:
            JSON string representation of the instance
        """
        return json.dumps(self.to_dict(), cls=CustomJSONEncoder)

    @classmethod
    def from_json(cls: Type[T], data: str) -> T:
        """
        Create an instance from a JSON string.

        Args:
            data: JSON string containing field values

        Returns:
            Instance of the class with values from the JSON string
        """
        return cls.from_dict(json.loads(data))

    def validate(self) -> None:
        """
        Validate the instance fields.

        Override this method in subclasses to implement custom validation logic.

        Raises:
            ValueError: If validation fails
        """
        pass
