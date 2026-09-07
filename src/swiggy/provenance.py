"""Evidence and provenance records for normalized Swiggy data."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from json import dumps
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Self, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from typing_extensions import TypeAliasType


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceState(StrEnum):
    """Strength of the endpoint evidence supporting a normalized value."""

    LIVE_VERIFIED = "LIVE VERIFIED"
    CAPTURED = "CAPTURED"
    STATIC_ONLY = "STATIC ONLY"
    AUTH_REQUIRED = "AUTH REQUIRED"
    RETIRED_BROKEN = "RETIRED/BROKEN"


class SourceEvidence(_FrozenModel):
    """Field-level evidence from a documented provider endpoint."""

    endpoint_id: str = Field(min_length=1)
    evidence_state: EvidenceState
    retrieved_at: AwareDatetime
    confidence: float = Field(ge=0.0, le=1.0)


class UnavailableField(_FrozenModel):
    """An explicit reason that a normalized field has no value."""

    field_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    sources: tuple[SourceEvidence, ...] = ()


JsonScalar: TypeAlias = str | int | float | bool | None
if TYPE_CHECKING:
    JsonValue: TypeAlias = (
        JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
    )
else:
    JsonValue = TypeAliasType(
        "JsonValue",
        JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"],
    )


def _freeze_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("conflict values must be JSON-compatible finite values")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError("conflict values must be JSON-compatible objects")
            frozen[key] = _freeze_json_value(nested_value)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise ValueError("conflict values must be JSON-compatible values")


def _json_value_for_serialization(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {
            key: _json_value_for_serialization(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, tuple):
        return [_json_value_for_serialization(item) for item in value]
    return value


def _json_value_for_comparison(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {
            key: _json_value_for_comparison(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, tuple):
        return [_json_value_for_comparison(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canonical_json_value(value: object) -> str:
    normalized = _json_value_for_comparison(_freeze_json_value(value))
    return dumps(normalized, allow_nan=False, separators=(",", ":"), sort_keys=True)


class FieldConflict(_FrozenModel):
    """Competing JSON-compatible values retained with their evidence."""

    field_name: str = Field(min_length=1)
    values: tuple[JsonValue, ...]
    sources: tuple[SourceEvidence, ...]

    @field_validator("values", mode="before")
    @classmethod
    def validate_and_copy_values(cls, value: object) -> tuple[JsonValue, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("conflict values must be a JSON-compatible sequence")
        return tuple(_freeze_json_value(item) for item in value)

    @field_validator("values")
    @classmethod
    def freeze_validated_values(
        cls, values: tuple[JsonValue, ...]
    ) -> tuple[JsonValue, ...]:
        return tuple(_freeze_json_value(value) for value in values)

    @field_serializer("values", when_used="json")
    def serialize_values(self, values: tuple[JsonValue, ...]) -> list[object]:
        return [_json_value_for_serialization(value) for value in values]

    @model_validator(mode="after")
    def validate_conflict(self) -> Self:
        if len(self.values) < 2:
            raise ValueError("a field conflict requires at least two values")
        if len(self.values) != len(self.sources):
            raise ValueError("each conflicting value requires source evidence")
        canonical_values = tuple(_canonical_json_value(value) for value in self.values)
        if len(set(canonical_values)) != len(canonical_values):
            raise ValueError("conflict values must be structurally distinct")
        return self


__all__ = [
    "EvidenceState",
    "FieldConflict",
    "JsonValue",
    "SourceEvidence",
    "UnavailableField",
]
