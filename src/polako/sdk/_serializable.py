"""Base serializable class for data models."""

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any, ClassVar, Dict, Optional, Type, TypeVar, Union, cast, get_args, get_origin
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

    A field may carry metadata (``dataclasses.field(metadata=...)``):

    * ``alias``: the name of the field on the wire. ``from_dict`` reads the alias first and falls back to the field
      name; ``to_dict`` / ``to_json`` write aliases when ``by_alias`` is true.
    * ``decode``: a callable that turns the raw wire value into the field value (e.g. to pick a class by a
      discriminator). Its exceptions propagate unchanged.

    A class that always speaks aliases on the wire sets ``serialize_by_alias = True``.
    """

    serialize_by_alias: ClassVar[bool] = False

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
            alias = f.metadata.get("alias")
            value = data[alias] if alias and alias in data else data.get(f.name)

            if value is None:
                init_args[f.name] = None
                continue

            decode = f.metadata.get("decode")
            if decode is not None:
                init_args[f.name] = decode(value)
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

    def to_dict(self, by_alias: Optional[bool] = None) -> Dict[str, Any]:
        """
        Convert instance to a dictionary.

        Args:
            by_alias: Use the wire names from the ``alias`` metadata. None means the class default
                (``serialize_by_alias``); nested models follow an explicit value, otherwise their own default.

        Returns:
            Dictionary representation of the instance
        """
        use_alias = self.serialize_by_alias if by_alias is None else by_alias
        result: Dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            key = (f.metadata.get("alias") if use_alias else None) or f.name
            if isinstance(value, list):
                result[key] = [cast(Serializable, v).to_dict(by_alias) if is_dataclass(v) else v for v in value]
            elif is_dataclass(value):
                result[key] = cast(Serializable, value).to_dict(by_alias)
            else:
                result[key] = value
        return result

    def to_json(self, by_alias: Optional[bool] = None) -> str:
        """
        Convert instance to a JSON string.

        Args:
            by_alias: See :meth:`to_dict`.

        Returns:
            JSON string representation of the instance
        """
        return json.dumps(self.to_dict(by_alias), cls=CustomJSONEncoder)

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
