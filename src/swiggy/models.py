"""Immutable normalized records for Swiggy Dineout data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, time
from types import MappingProxyType
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from swiggy.provenance import (
    FieldConflict,
    SourceEvidence,
    UnavailableField,
    _canonical_json_value,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Coordinates(_FrozenModel):
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)


class OperatingHours(_FrozenModel):
    day: str = Field(min_length=1)
    opens_at: time | None = None
    closes_at: time | None = None
    is_open: bool | None = None


class Offer(_FrozenModel):
    title: str = Field(min_length=1)
    description: str | None = None
    discount_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    minimum_bill: float | None = Field(default=None, ge=0.0)
    valid_from: date | None = None
    valid_until: date | None = None
    restrictions: tuple[str, ...] = ()
    source: SourceEvidence

    @model_validator(mode="after")
    def validate_validity_window(self) -> Self:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from > self.valid_until
        ):
            raise ValueError("valid_from must not exceed valid_until")
        return self


class ReviewSample(_FrozenModel):
    rating: float = Field(ge=0.0, le=5.0)
    text: str | None = None
    reviewed_at: AwareDatetime | None = None
    source: SourceEvidence


class MenuReference(_FrozenModel):
    label: str = Field(min_length=1)
    provider_menu_id: str | None = None
    url: str | None = None
    source: SourceEvidence


class VenueAttributes(_FrozenModel):
    bar: bool | None = None
    live_music: bool | None = None
    rooftop: bool | None = None
    outdoor_seating: bool | None = None
    dance_floor: bool | None = None
    late_night: bool | None = None
    facilities: tuple[str, ...] = ()


def _is_concrete_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, tuple, list, set, frozenset, Mapping)):
        return bool(value)
    return True


class VenueRecord(_FrozenModel):
    provider: Literal["swiggy"] = "swiggy"
    provider_venue_id: str = Field(min_length=1)
    cross_provider_id: str | None = None
    name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    coordinates: Coordinates | None = None
    locality: str | None = None
    display_address: str | None = None
    cuisines: tuple[str, ...] = ()
    cost_for_two: float | None = Field(default=None, ge=0.0)
    currency: str | None = None
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    rating_count: int | None = Field(default=None, ge=0)
    operating_hours: tuple[OperatingHours, ...] = ()
    currently_available: bool | None = None
    offers: tuple[Offer, ...] = ()
    menu_references: tuple[MenuReference, ...] = ()
    attributes: VenueAttributes | None = None
    review_samples: tuple[ReviewSample, ...] = ()
    retrieved_at: AwareDatetime
    provenance: Mapping[str, SourceEvidence] = Field(
        default_factory=lambda: MappingProxyType({})
    )
    unavailable_fields: tuple[UnavailableField, ...] = ()
    conflicts: tuple[FieldConflict, ...] = ()

    @field_validator("provenance")
    @classmethod
    def freeze_provenance(
        cls, provenance: Mapping[str, SourceEvidence]
    ) -> Mapping[str, SourceEvidence]:
        return MappingProxyType(dict(provenance))

    @field_serializer("provenance", when_used="json")
    def serialize_provenance(
        self, provenance: Mapping[str, SourceEvidence]
    ) -> dict[str, SourceEvidence]:
        return dict(provenance)

    @model_validator(mode="after")
    def validate_field_declarations(self) -> Self:
        declaration_fields = {"provenance", "unavailable_fields", "conflicts"}
        normalized_fields = set(type(self).model_fields) - declaration_fields
        unavailable_names = [item.field_name for item in self.unavailable_fields]
        conflict_names = [item.field_name for item in self.conflicts]

        declared_names = (
            set(self.provenance) | set(unavailable_names) | set(conflict_names)
        )
        unknown_names = declared_names - normalized_fields
        if unknown_names:
            unknown = ", ".join(sorted(unknown_names))
            raise ValueError(f"not a normalized VenueRecord field: {unknown}")

        if len(unavailable_names) != len(set(unavailable_names)):
            raise ValueError("duplicate unavailable field declaration")
        if len(conflict_names) != len(set(conflict_names)):
            raise ValueError("duplicate conflict field declaration")

        unavailable_set = set(unavailable_names)
        conflict_set = set(conflict_names)
        if overlap := unavailable_set & conflict_set:
            fields = ", ".join(sorted(overlap))
            raise ValueError(
                f"fields cannot be both unavailable and conflicting: {fields}"
            )
        if overlap := unavailable_set & set(self.provenance):
            fields = ", ".join(sorted(overlap))
            raise ValueError(f"fields cannot be both unavailable and sourced: {fields}")

        for field_name in unavailable_names:
            if _is_concrete_value(getattr(self, field_name)):
                raise ValueError(
                    f"unavailable field {field_name!r} has a concrete value"
                )

        for conflict in self.conflicts:
            selected_value = getattr(self, conflict.field_name)
            if not _is_concrete_value(selected_value):
                raise ValueError(
                    f"conflicting field {conflict.field_name!r} "
                    "requires a concrete selected value"
                )

            selected_json_value = self.model_dump(
                mode="json", include={conflict.field_name}
            )[conflict.field_name]
            selected_canonical = _canonical_json_value(selected_json_value)
            matching_indexes = tuple(
                index
                for index, candidate in enumerate(conflict.values)
                if _canonical_json_value(candidate) == selected_canonical
            )
            if not matching_indexes:
                raise ValueError(
                    f"selected value for {conflict.field_name!r} must be among "
                    "its retained conflict values"
                )

            selected_source = self.provenance.get(conflict.field_name)
            if selected_source is not None and not any(
                conflict.sources[index] == selected_source for index in matching_indexes
            ):
                raise ValueError(
                    f"selected provenance source and value for "
                    f"{conflict.field_name!r} must match the same retained candidate"
                )
        return self


class EnrichmentFailure(_FrozenModel):
    provider: Literal["swiggy"] = "swiggy"
    provider_venue_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    endpoint_id: str | None = None
    retryable: bool
    retrieved_at: AwareDatetime


__all__ = [
    "Coordinates",
    "EnrichmentFailure",
    "MenuReference",
    "Offer",
    "OperatingHours",
    "ReviewSample",
    "VenueAttributes",
    "VenueRecord",
]
