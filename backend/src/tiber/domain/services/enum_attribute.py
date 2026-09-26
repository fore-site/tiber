from enum import StrEnum
from typing import Any

from ..exceptions import InvalidEntityAttributeError


def set_enum_attribute(
    obj: Any, field_name: str, enum_cls: type[StrEnum], raw_value: str
) -> None:
    """Safely converts a string to an Enum and assigns it to a frozen dataclass field."""
    try:
        normalized_value = raw_value.lower()
        enum_value = enum_cls(normalized_value)
        object.__setattr__(obj, field_name, enum_value)
    except ValueError as e:
        raise InvalidEntityAttributeError(
            message=f"Invalid value '{raw_value}' provided for field '{field_name}' on entity '{obj.__class__.__name__}'"
        ) from e
