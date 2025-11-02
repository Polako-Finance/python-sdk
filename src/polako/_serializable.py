import json
from dataclasses import fields, is_dataclass
from typing import Any, Dict, Type, TypeVar, cast, get_args, get_origin

T = TypeVar("T", bound="Serializable")


class Serializable:
    @classmethod
    def from_dict(cls: Type[T], data: dict) -> T:
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
            else:
                init_args[f.name] = value

        return cls(**init_args)

    def to_dict(self) -> Dict[str, Any]:
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
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls: Type[T], data: str) -> T:
        return cls.from_dict(json.loads(data))

    def validate(self) -> None:
        pass
