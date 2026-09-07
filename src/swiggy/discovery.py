"""Pure parsing and bounded pagination for guest Dineout discovery."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from swiggy.errors import ProviderResponseError, SchemaDriftError
from swiggy.models import Coordinates, VenueRecord
from swiggy.provenance import EvidenceState, SourceEvidence, UnavailableField
from swiggy.transport import TransportResponse

_OPTIONAL_DISCOVERY_FIELDS = (
    "coordinates",
    "cuisines",
    "cost_for_two",
    "locality",
    "rating",
    "rating_count",
)


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    """A parsed page and its optional provider pagination token."""

    venues: tuple[VenueRecord, ...]
    next_cursor: str | None = None


class DiscoveryTransport(Protocol):
    def request(self, endpoint_id: str, **kwargs: object) -> TransportResponse: ...


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _schema_error(evidence: SourceEvidence, detail: str) -> SchemaDriftError:
    return SchemaDriftError(f"{evidence.endpoint_id} discovery: {detail}")


def _as_mapping(
    value: object, evidence: SourceEvidence, detail: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _schema_error(evidence, detail)
    return value


def _cursor(payload: Mapping[str, object]) -> str | None:
    direct = payload.get("next_offset")
    if direct is not None and not isinstance(direct, bool):
        return str(direct)
    pagination = payload.get("pagination")
    if isinstance(pagination, Mapping):
        value = pagination.get("nextCursor")
        if value is not None and not isinstance(value, bool):
            return str(value)
    page_offset = payload.get("page_offset")
    if isinstance(page_offset, Mapping):
        value = page_offset.get("next_offset")
        if value is not None and not isinstance(value, bool):
            return str(value)
    return None


def _field_value(card: Mapping[str, object], field_name: str) -> object:
    aliases = {
        "provider_venue_id": ("provider_venue_id", "id", "restaurantId"),
        "cost_for_two": ("cost_for_two", "costForTwo"),
        "rating_count": ("rating_count", "ratingCount"),
    }
    for key in aliases.get(field_name, (field_name,)):
        if key in card:
            return card[key]
    return None


def _venue_from_card(
    card: Mapping[str, object], evidence: SourceEvidence
) -> VenueRecord:
    provider_id = _field_value(card, "provider_venue_id")
    name = card.get("name")
    if (
        isinstance(provider_id, bool)
        or not isinstance(provider_id, (str, int))
        or not str(provider_id).strip()
    ):
        raise _schema_error(evidence, "card is missing provider venue id")
    if not isinstance(name, str) or not name.strip():
        raise _schema_error(evidence, "card is missing name")

    values: dict[str, Any] = {
        "provider_venue_id": str(provider_id),
        "name": name.strip(),
        "normalized_name": _normalize_name(name),
        "retrieved_at": evidence.retrieved_at,
    }
    provenance: dict[str, SourceEvidence] = {}
    for field_name in ("provider_venue_id", "name", "normalized_name"):
        provenance[field_name] = evidence

    coordinates = card.get("coordinates")
    if coordinates is not None:
        coordinate_map = coordinates if isinstance(coordinates, Mapping) else None
        if coordinate_map is not None:
            latitude = coordinate_map.get("latitude", coordinate_map.get("lat"))
            longitude = coordinate_map.get(
                "longitude", coordinate_map.get("lon", coordinate_map.get("lng"))
            )
        elif isinstance(coordinates, Sequence) and not isinstance(
            coordinates, (str, bytes)
        ):
            latitude = coordinates[0] if len(coordinates) > 0 else None
            longitude = coordinates[1] if len(coordinates) > 1 else None
        else:
            latitude = longitude = None
        if latitude is None or longitude is None:
            raise _schema_error(
                evidence, "coordinates must contain latitude and longitude"
            )
        try:
            values["coordinates"] = Coordinates(
                latitude=float(str(latitude)), longitude=float(str(longitude))
            )
        except (TypeError, ValueError, ValidationError):
            raise _schema_error(evidence, "invalid coordinates") from None
        provenance["coordinates"] = evidence

    cuisines = card.get("cuisines")
    if cuisines is not None:
        if not isinstance(cuisines, Sequence) or isinstance(cuisines, (str, bytes)):
            raise _schema_error(evidence, "cuisines must be a sequence")
        values["cuisines"] = tuple(str(item) for item in cuisines)
        provenance["cuisines"] = evidence

    for field_name in ("locality", "rating", "cost_for_two", "rating_count"):
        raw = _field_value(card, field_name)
        if raw is None:
            continue
        try:
            if field_name == "locality":
                if not isinstance(raw, str):
                    raise TypeError
                values[field_name] = raw
            elif field_name == "rating_count":
                values[field_name] = int(str(raw))
            else:
                values[field_name] = float(str(raw))
        except (TypeError, ValueError):
            raise _schema_error(evidence, f"invalid {field_name}") from None
        provenance[field_name] = evidence

    unavailable = tuple(
        UnavailableField(
            field_name=field_name,
            reason="not present in discovery response",
            sources=(evidence,),
        )
        for field_name in _OPTIONAL_DISCOVERY_FIELDS
        if field_name not in values
    )
    return VenueRecord(**values, provenance=provenance, unavailable_fields=unavailable)


def parse_discovery_page(
    payload: Mapping[str, object], evidence: SourceEvidence
) -> DiscoveryPage:
    """Parse one provider payload without performing I/O or retaining raw data."""

    root = _as_mapping(payload, evidence, "payload must be an object")
    status = root.get("status_message", "success")
    if status != "success" or root.get("error") is not None:
        raise ProviderResponseError(f"{evidence.endpoint_id} returned a provider error")
    cards = root.get("cards")
    if not isinstance(cards, Sequence) or isinstance(cards, (str, bytes)):
        raise _schema_error(evidence, "cards must be a sequence")
    venues = tuple(
        _venue_from_card(
            _as_mapping(card, evidence, "card must be an object"), evidence
        )
        for card in cards
    )
    return DiscoveryPage(venues=venues, next_cursor=_cursor(root))


def _merge_venue(old: VenueRecord, new: VenueRecord) -> VenueRecord:
    merged = {
        field_name: getattr(old, field_name) for field_name in VenueRecord.model_fields
    }
    merged_provenance = dict(old.provenance)
    merged_unavailable = {item.field_name: item for item in old.unavailable_fields}
    for field_name in _OPTIONAL_DISCOVERY_FIELDS:
        candidate = getattr(new, field_name)
        old_value = getattr(old, field_name)
        if (
            candidate is not None
            and candidate != ()
            and (old_value is None or old_value == ())
        ):
            merged[field_name] = candidate
            if field_name in new.provenance:
                merged_provenance[field_name] = new.provenance[field_name]
            merged_unavailable.pop(field_name, None)
    merged["provenance"] = merged_provenance
    merged["unavailable_fields"] = tuple(merged_unavailable.values())
    return VenueRecord.model_validate(merged)


def dedupe_venues(pages: Sequence[DiscoveryPage]) -> tuple[VenueRecord, ...]:
    """Deduplicate by stable provider ID while retaining first-seen order."""

    by_id: dict[str, VenueRecord] = {}
    for page in pages:
        for venue in page.venues:
            if venue.provider_venue_id in by_id:
                by_id[venue.provider_venue_id] = _merge_venue(
                    by_id[venue.provider_venue_id], venue
                )
            else:
                by_id[venue.provider_venue_id] = venue
    return tuple(by_id.values())


class DiscoveryService:
    """Bounded discovery service backed by the safe transport abstraction."""

    def __init__(self, transport: DiscoveryTransport) -> None:
        self.transport = transport

    def nearby(
        self, *, max_pages: int = 10, max_results: int = 100
    ) -> tuple[VenueRecord, ...]:
        if max_pages < 1 or max_results < 1:
            return ()
        pages: list[DiscoveryPage] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(max_pages):
            params: dict[str, str] = {}
            if cursor is not None:
                params["offset"] = cursor
            response = self.transport.request("dineout-discovery", query_params=params)
            payload: object = response.json_payload
            if payload is None:
                try:
                    payload = json.loads(response.text or "")
                except json.JSONDecodeError:
                    raise SchemaDriftError(
                        f"{response.endpoint_id} discovery: response was not JSON"
                    ) from None
            response_evidence = _evidence(response)
            page = parse_discovery_page(
                _as_mapping(payload, response_evidence, "payload must be an object"),
                response_evidence,
            )
            pages.append(page)
            venues = dedupe_venues(pages)
            if len(venues) >= max_results:
                return venues[:max_results]
            if page.next_cursor is None or page.next_cursor in seen_cursors:
                return venues[:max_results]
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        return dedupe_venues(pages)[:max_results]


def _evidence(response: TransportResponse) -> SourceEvidence:
    return SourceEvidence(
        endpoint_id=response.endpoint_id,
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=datetime.now(UTC),
        confidence=0.9,
    )


__all__ = ["DiscoveryPage", "DiscoveryService", "dedupe_venues", "parse_discovery_page"]
