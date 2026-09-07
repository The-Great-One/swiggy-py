from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from swiggy.models import (
    Coordinates,
    EnrichmentFailure,
    MenuReference,
    Offer,
    OperatingHours,
    ReviewSample,
    VenueAttributes,
    VenueRecord,
)
from swiggy.provenance import (
    EvidenceState,
    FieldConflict,
    SourceEvidence,
    UnavailableField,
)

RETRIEVED_AT = datetime(2026, 9, 6, 8, 30, tzinfo=UTC)


def evidence(endpoint_id: str = "dineout-discovery") -> SourceEvidence:
    return SourceEvidence(
        endpoint_id=endpoint_id,
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        confidence=0.95,
    )


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    coordinates = Coordinates(latitude=28.5, longitude=77.1)

    with pytest.raises(ValidationError):
        coordinates.latitude = 0.0

    with pytest.raises(ValidationError):
        Coordinates.model_validate(
            {"latitude": 28.5, "longitude": 77.1, "guessed": True}
        )


def test_venue_provenance_is_defensively_copied_and_immutable() -> None:
    discovery = evidence()
    original = {"rating": discovery}
    venue = VenueRecord(
        provider_venue_id="swiggy-123",
        name="Example Cafe",
        normalized_name="example cafe",
        rating=4.2,
        retrieved_at=RETRIEVED_AT,
        provenance=original,
    )

    original["name"] = evidence("dineout-details")
    original.clear()

    assert isinstance(venue.provenance, MappingProxyType)
    assert tuple(venue.provenance) == ("rating",)
    assert venue.provenance["rating"] == discovery
    with pytest.raises(TypeError):
        venue.provenance["name"] = discovery  # type: ignore[index]
    with pytest.raises(AttributeError):
        venue.provenance.clear()  # type: ignore[attr-defined]
    assert venue.model_dump(mode="json")["provenance"]["rating"]["endpoint_id"] == (
        "dineout-discovery"
    )


def test_retrieval_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        SourceEvidence(
            endpoint_id="dineout-discovery",
            evidence_state=EvidenceState.CAPTURED,
            retrieved_at=datetime(2026, 9, 6, 8, 30),
            confidence=0.8,
        )

    with pytest.raises(ValidationError):
        VenueRecord(
            provider_venue_id="swiggy-123",
            name="Example Cafe",
            normalized_name="example cafe",
            retrieved_at=datetime(2026, 9, 6, 8, 30),
        )


def test_offer_supports_unknown_validity_and_optional_restrictions() -> None:
    offer = Offer(title="20% off", source=evidence())

    assert offer.valid_from is None
    assert offer.valid_until is None
    assert offer.minimum_bill is None
    assert offer.restrictions == ()


def test_offer_rejects_an_inverted_validity_window() -> None:
    with pytest.raises(ValidationError, match="valid_from must not exceed valid_until"):
        Offer(
            title="Expired before it starts",
            valid_from=date(2026, 9, 7),
            valid_until=date(2026, 9, 6),
            source=evidence(),
        )


def test_supporting_value_models_retain_explicit_provider_data() -> None:
    hours = OperatingHours(day="monday", opens_at=time(18, 0), closes_at=time(1, 0))
    review = ReviewSample(
        rating=4.5,
        text="Synthetic review",
        reviewed_at=RETRIEVED_AT,
        source=evidence("dineout-reviews"),
    )
    menu = MenuReference(
        label="Dinner menu",
        provider_menu_id="menu-1",
        source=evidence("dineout-menu"),
    )
    attributes = VenueAttributes(
        bar=True,
        live_music=None,
        rooftop=False,
        outdoor_seating=True,
        dance_floor=None,
        late_night=None,
    )

    assert hours.closes_at == time(1, 0)
    assert review.reviewed_at == RETRIEVED_AT
    assert menu.provider_menu_id == "menu-1"
    assert attributes.live_music is None


def test_enrichment_failure_is_structured_and_immutable() -> None:
    failure = EnrichmentFailure(
        provider_venue_id="swiggy-123",
        stage="reviews",
        reason="authentication required",
        endpoint_id="dineout-reviews",
        retryable=False,
        retrieved_at=RETRIEVED_AT,
    )

    assert failure.provider == "swiggy"
    with pytest.raises(ValidationError):
        failure.reason = "different"


def test_coordinates_and_confidence_are_bounded() -> None:
    with pytest.raises(ValidationError):
        Coordinates(latitude=91, longitude=77.1)

    with pytest.raises(ValidationError):
        SourceEvidence(
            endpoint_id="dineout-discovery",
            evidence_state=EvidenceState.STATIC_ONLY,
            retrieved_at=RETRIEVED_AT,
            confidence=1.1,
        )


def test_unknown_fields_have_explicit_absence_reasons() -> None:
    unavailable = UnavailableField(
        field_name="rating_count",
        reason="not present in discovery response",
        sources=(evidence(),),
    )
    venue = VenueRecord(
        provider_venue_id="swiggy-123",
        name="Example Cafe",
        normalized_name="example cafe",
        retrieved_at=RETRIEVED_AT,
        unavailable_fields=(unavailable,),
    )

    assert venue.rating_count is None
    assert venue.unavailable_fields[0].reason == ("not present in discovery response")


def test_conflicts_retain_each_value_and_its_source() -> None:
    conflict = FieldConflict(
        field_name="rating",
        values=(4.2, 4.4),
        sources=(evidence(), evidence("dineout-details")),
    )

    assert conflict.values == (4.2, 4.4)
    assert tuple(source.endpoint_id for source in conflict.sources) == (
        "dineout-discovery",
        "dineout-details",
    )

    with pytest.raises(ValidationError):
        FieldConflict(
            field_name="rating",
            values=(4.2,),
            sources=(evidence(),),
        )


@pytest.mark.parametrize(
    "values",
    [
        (4.2, 4.2),
        (1, 1.0),
        (4.2, 4.4, 4.2),
        (
            {"labels": ["top"], "metadata": {"rank": 1}},
            {"metadata": {"rank": 1}, "labels": ("top",)},
        ),
    ],
)
def test_conflicts_require_structurally_distinct_json_values(
    values: tuple[object, ...],
) -> None:
    with pytest.raises(ValidationError, match="structurally distinct"):
        FieldConflict.model_validate(
            {
                "field_name": "attributes",
                "values": values,
                "sources": tuple(
                    evidence(f"dineout-source-{index}") for index in range(len(values))
                ),
            }
        )


def test_conflict_values_are_deeply_copied_and_recursively_immutable() -> None:
    labels: list[object] = ["top", {"verified": True}]
    metadata: dict[str, object] = {"rank": 1}
    original: dict[str, object] = {"labels": labels, "metadata": metadata}
    conflict = FieldConflict.model_validate(
        {
            "field_name": "attributes",
            "values": (original, None),
            "sources": (evidence(), evidence("dineout-details")),
        }
    )

    labels.append("mutated")
    metadata["rank"] = 99

    first = conflict.values[0]
    assert isinstance(first, MappingProxyType)
    assert first["labels"] == ("top", MappingProxyType({"verified": True}))
    frozen_metadata = first["metadata"]
    assert isinstance(frozen_metadata, Mapping)
    assert frozen_metadata["rank"] == 1
    with pytest.raises(TypeError):
        frozen_metadata["rank"] = 2  # type: ignore[index]


def test_conflict_values_preserve_supported_json_roundtrip_shapes() -> None:
    values = (
        None,
        {
            "string": "value",
            "boolean": True,
            "integer": 1,
            "number": 1.5,
            "array": [False, None, {"nested": "value"}],
        },
    )
    conflict = FieldConflict.model_validate(
        {
            "field_name": "attributes",
            "values": values,
            "sources": (evidence(), evidence("dineout-details")),
        }
    )

    assert conflict.model_dump(mode="json")["values"] == [
        None,
        {
            "string": "value",
            "boolean": True,
            "integer": 1,
            "number": 1.5,
            "array": [False, None, {"nested": "value"}],
        },
    ]


@pytest.mark.parametrize(
    "invalid_value", [object(), float("inf"), float("-inf"), float("nan")]
)
def test_conflict_values_reject_non_json_values(invalid_value: object) -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        FieldConflict.model_validate(
            {
                "field_name": "rating",
                "values": (4.2, invalid_value),
                "sources": (evidence(), evidence("dineout-details")),
            }
        )
