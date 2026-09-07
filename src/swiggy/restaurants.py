"""Pure parsing of guest Dineout restaurant detail responses."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, time
from math import isfinite
from types import MappingProxyType
from typing import Any, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from swiggy.errors import ProviderResponseError, SchemaDriftError
from swiggy.models import Coordinates, MenuReference, OperatingHours, VenueAttributes
from swiggy.provenance import SourceEvidence, UnavailableField

_OPTIONAL_FIELDS = (
    "coordinates",
    "display_address",
    "locality",
    "cuisines",
    "cost_for_two",
    "rating",
    "rating_count",
    "operating_hours",
    "menu_references",
    "attributes",
)
_UNAVAILABLE_REASON = "not present in restaurant detail response"


class RestaurantDetail(BaseModel):
    """Immutable, evidence-bearing partial detail enrichment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_venue_id: str = Field(min_length=1)
    name: str | None = None
    coordinates: Coordinates | None = None
    display_address: str | None = None
    locality: str | None = None
    cuisines: tuple[str, ...] = ()
    cost_for_two: float | None = Field(default=None, ge=0.0)
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    rating_count: int | None = Field(default=None, ge=0)
    operating_hours: tuple[OperatingHours, ...] = ()
    menu_references: tuple[MenuReference, ...] = ()
    attributes: VenueAttributes | None = None
    retrieved_at: AwareDatetime
    provenance: Mapping[str, SourceEvidence] = Field(
        default_factory=lambda: MappingProxyType({})
    )
    unavailable_fields: tuple[UnavailableField, ...] = ()

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
        unavailable_names = [item.field_name for item in self.unavailable_fields]
        if len(unavailable_names) != len(set(unavailable_names)):
            raise ValueError("duplicate unavailable field declaration")
        declared_names = set(unavailable_names) | set(self.provenance)
        unknown_names = declared_names - (
            set(_OPTIONAL_FIELDS) | {"provider_venue_id", "name", "retrieved_at"}
        )
        if unknown_names:
            raise ValueError(
                "not a normalized RestaurantDetail field: "
                + ", ".join(sorted(unknown_names))
            )
        overlap = set(unavailable_names) & set(self.provenance)
        if overlap:
            raise ValueError(
                "fields cannot be both unavailable and sourced: "
                + ", ".join(sorted(overlap))
            )
        for field_name in unavailable_names:
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, (tuple, list)) or value):
                raise ValueError(
                    f"unavailable field {field_name!r} has a concrete value"
                )
        return self


def _schema_error(evidence: SourceEvidence, detail: str) -> SchemaDriftError:
    return SchemaDriftError(f"{evidence.endpoint_id} restaurant detail: {detail}")


def _as_mapping(
    value: object, evidence: SourceEvidence, detail: str = "payload must be an object"
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _schema_error(evidence, detail)
    return value


def _first(payload: Mapping[str, object], *names: str) -> tuple[bool, object]:
    for name in names:
        if name in payload:
            return True, payload[name]
    return False, None


def _text(
    value: object, evidence: SourceEvidence, field_name: str, *, required: bool = False
) -> str | None:
    if value is None:
        if required:
            raise _schema_error(evidence, f"missing {field_name}")
        return None
    if not isinstance(value, str) or not value.strip():
        raise _schema_error(evidence, f"invalid {field_name}")
    return value.strip()


def _number(value: object, evidence: SourceEvidence, field_name: str) -> float:
    if isinstance(value, bool):
        raise _schema_error(evidence, f"invalid {field_name}")
    try:
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            match = re.search(r"-?\d+(?:[,.]\d+)*", value)
            if match is None:
                raise ValueError
            result = float(match.group(0).replace(",", ""))
        else:
            raise TypeError
    except (TypeError, ValueError):
        raise _schema_error(evidence, f"invalid {field_name}") from None
    if not isfinite(result):
        raise _schema_error(evidence, f"invalid {field_name}")
    return result


def _count(value: object, evidence: SourceEvidence) -> int:
    if isinstance(value, bool):
        raise _schema_error(evidence, "invalid rating_count")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([0-9]+(?:[.,][0-9]+)?)\s*([kKmMbB])?.*", value)
        if match:
            amount = float(match.group(1).replace(",", ""))
            multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(
                (match.group(2) or "").lower(), 1
            )
            return int(amount * multiplier)
    raise _schema_error(evidence, "invalid rating_count")


def _coordinates(value: object, evidence: SourceEvidence) -> Coordinates:
    if isinstance(value, Mapping):
        latitude = value.get("latitude", value.get("lat"))
        longitude = value.get(
            "longitude", value.get("longitude", value.get("lon", value.get("lng")))
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        latitude = value[0] if len(value) > 0 else None
        longitude = value[1] if len(value) > 1 else None
    else:
        latitude = longitude = None
    if latitude is None or longitude is None:
        raise _schema_error(evidence, "coordinates must contain latitude and longitude")
    try:
        return Coordinates(
            latitude=_number(latitude, evidence, "coordinates"),
            longitude=_number(longitude, evidence, "coordinates"),
        )
    except ValidationError:
        raise _schema_error(evidence, "invalid coordinates") from None


def _clock(value: object, evidence: SourceEvidence, field_name: str) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        raise _schema_error(evidence, f"invalid {field_name}")
    text = value.strip()
    for candidate in (text, text.upper()):
        try:
            return time.fromisoformat(candidate)
        except ValueError:
            pass
        for fmt in ("%I:%M %p", "%I %p"):
            try:
                parsed = datetime.strptime(candidate, fmt).time()
                return time(parsed.hour, parsed.minute, parsed.second)
            except ValueError:
                continue
    raise _schema_error(evidence, f"invalid {field_name}")


def _hours(value: object, evidence: SourceEvidence) -> tuple[OperatingHours, ...]:
    if isinstance(value, Mapping):
        if any(key in value for key in ("closing_label", "opening_label", "label")):
            return ()
        entries: list[object] = [
            dict(item, day=day) if isinstance(item, Mapping) else item
            for day, item in value.items()
        ]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        entries = list(value)
    else:
        raise _schema_error(evidence, "hours must be an object or sequence")

    parsed: list[OperatingHours] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        day = _text(entry.get("day", entry.get("day_name")), evidence, "hours day")
        if day is None:
            continue
        opens = _clock(
            entry.get("opens_at", entry.get("open", entry.get("opening_time"))),
            evidence,
            "hours opening time",
        )
        closes = _clock(
            entry.get("closes_at", entry.get("close", entry.get("closing_time"))),
            evidence,
            "hours closing time",
        )
        if opens is None and closes is None and "is_open" not in entry:
            continue
        is_open = entry.get("is_open")
        if is_open is not None and not isinstance(is_open, bool):
            raise _schema_error(evidence, "invalid hours is_open")
        parsed.append(
            OperatingHours(day=day, opens_at=opens, closes_at=closes, is_open=is_open)
        )
    return tuple(parsed)


def _menus(value: object, evidence: SourceEvidence) -> tuple[MenuReference, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _schema_error(evidence, "menu sections must be a sequence")
    parsed: list[MenuReference] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise _schema_error(evidence, "menu section must be an object")
        label = _text(
            entry.get("label", entry.get("name", entry.get("title"))),
            evidence,
            "menu label",
            required=True,
        )
        menu_id = _text(
            entry.get("provider_menu_id", entry.get("menu_id", entry.get("id"))),
            evidence,
            "provider menu id",
        )
        url = _text(entry.get("url", entry.get("menu_url")), evidence, "menu url")
        assert label is not None
        parsed.append(
            MenuReference(
                label=label,
                provider_menu_id=menu_id,
                url=url,
                source=evidence,
            )
        )
    return tuple(parsed)


def _attributes(value: object, evidence: SourceEvidence) -> VenueAttributes:
    recognized: dict[str, bool | None] = {}
    facilities: list[str] = []
    if isinstance(value, Mapping):
        for field_name in VenueAttributes.model_fields:
            if field_name == "facilities":
                continue
            if field_name in value:
                raw = value[field_name]
                if not isinstance(raw, bool) and raw is not None:
                    raise _schema_error(evidence, f"invalid attribute {field_name}")
                recognized[field_name] = raw
        raw_facilities = value.get("facilities", ())
        value = raw_facilities
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _schema_error(evidence, "amenities must be a sequence")
    aliases: dict[str, str] = {
        "alcohol served": "bar",
        "bar": "bar",
        "live music": "live_music",
        "rooftop": "rooftop",
        "outdoor seating": "outdoor_seating",
        "dance floor": "dance_floor",
        "late night": "late_night",
        "late-night": "late_night",
    }
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _schema_error(evidence, "amenities must contain non-empty strings")
        label = item.strip()
        mapped_field: str | None = aliases.get(re.sub(r"\s+", " ", label.casefold()))
        if mapped_field is None:
            facilities.append(label)
        else:
            recognized[mapped_field] = True
    return VenueAttributes(**recognized, facilities=tuple(facilities))


def parse_restaurant_detail(
    payload: Mapping[str, object], evidence: SourceEvidence
) -> RestaurantDetail:
    """Parse a detail payload without retaining or exposing its raw contents."""

    root = _as_mapping(payload, evidence)
    status = root.get("status_message", "success")
    if status != "success" or root.get("error") is not None:
        raise ProviderResponseError(f"{evidence.endpoint_id} returned a provider error")

    provider_present, provider_raw = _first(
        root, "provider_venue_id", "restaurant_id", "restaurantId", "id"
    )
    if not provider_present or isinstance(provider_raw, bool):
        raise _schema_error(evidence, "missing provider venue id")
    provider_id = _text(provider_raw, evidence, "provider venue id", required=True)
    assert provider_id is not None

    values: dict[str, Any] = {
        "provider_venue_id": provider_id,
        "retrieved_at": evidence.retrieved_at,
    }
    provenance: dict[str, SourceEvidence] = {"provider_venue_id": evidence}
    name_present, name_raw = _first(root, "name", "restaurant_name", "restaurantName")
    if name_present and name_raw is not None:
        values["name"] = _text(name_raw, evidence, "name", required=True)
        provenance["name"] = evidence

    def set_optional(field_name: str, aliases: tuple[str, ...], parser: Any) -> None:
        present, raw = _first(root, *aliases)
        if not present or raw is None:
            return
        parsed = parser(raw)
        if field_name == "operating_hours" and parsed == ():
            return
        values[field_name] = parsed
        provenance[field_name] = evidence

    set_optional(
        "coordinates", ("coordinates",), lambda raw: _coordinates(raw, evidence)
    )
    set_optional(
        "display_address",
        ("display_address", "displayAddress", "address"),
        lambda raw: _text(raw, evidence, "display address", required=True),
    )
    set_optional(
        "locality",
        ("locality", "area", "neighborhood"),
        lambda raw: _text(raw, evidence, "locality", required=True),
    )
    set_optional(
        "cuisines", ("cuisines",), lambda raw: _string_tuple(raw, evidence, "cuisines")
    )
    set_optional(
        "cost_for_two",
        ("cost_for_two", "costForTwo"),
        lambda raw: _number(raw, evidence, "cost_for_two"),
    )
    set_optional("rating", ("rating",), lambda raw: _number(raw, evidence, "rating"))
    set_optional(
        "rating_count",
        ("rating_count", "ratingCount", "rating_count_label"),
        lambda raw: _count(raw, evidence),
    )
    set_optional(
        "operating_hours",
        ("operating_hours", "operatingHours", "hours"),
        lambda raw: _hours(raw, evidence),
    )
    set_optional(
        "menu_references",
        ("menu_references", "menuReferences", "menu_sections", "menuSections", "menu"),
        lambda raw: _menus(raw, evidence),
    )
    set_optional(
        "attributes",
        ("attributes", "amenities", "facilities"),
        lambda raw: _attributes(raw, evidence),
    )

    unavailable = tuple(
        UnavailableField(
            field_name=field_name,
            reason=_UNAVAILABLE_REASON,
            sources=(evidence,),
        )
        for field_name in _OPTIONAL_FIELDS
        if field_name not in values
    )
    try:
        return RestaurantDetail(
            **values, provenance=provenance, unavailable_fields=unavailable
        )
    except ValidationError:
        raise _schema_error(
            evidence, "restaurant detail contains invalid normalized values"
        ) from None


def _string_tuple(
    value: object, evidence: SourceEvidence, field_name: str
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _schema_error(evidence, f"{field_name} must be a sequence")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _schema_error(
                evidence, f"{field_name} must contain non-empty strings"
            )
        result.append(item.strip())
    return tuple(result)


__all__ = ["RestaurantDetail", "parse_restaurant_detail"]
