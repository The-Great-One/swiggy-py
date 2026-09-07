from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from swiggy.errors import (
    ConfigurationError,
    ProviderResponseError,
    SchemaDriftError,
    SwiggyError,
    TransportError,
    UnsafeEndpointError,
)
from swiggy.models import Coordinates, Offer, VenueRecord
from swiggy.provenance import (
    EvidenceState,
    FieldConflict,
    SourceEvidence,
    UnavailableField,
)

RETRIEVED_AT = datetime(2026, 9, 6, 8, 30, tzinfo=UTC)


def source(endpoint_id: str) -> SourceEvidence:
    return SourceEvidence(
        endpoint_id=endpoint_id,
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        confidence=1.0,
    )


def test_venue_contract_keeps_provider_identity_and_field_provenance() -> None:
    discovery = source("dineout-discovery")
    details = source("dineout-details")
    venue = VenueRecord(
        provider_venue_id="swiggy-123",
        cross_provider_id="future-aggregator-456",
        name="Example Cafe",
        normalized_name="example cafe",
        coordinates=Coordinates(latitude=28.5, longitude=77.1),
        rating=4.2,
        offers=(Offer(title="20% off", source=details),),
        retrieved_at=RETRIEVED_AT,
        provenance={"rating": discovery, "offers": details},
        conflicts=(
            FieldConflict(
                field_name="rating",
                values=(4.2, 4.4),
                sources=(discovery, details),
            ),
        ),
    )

    assert venue.provider == "swiggy"
    assert venue.provider_venue_id == "swiggy-123"
    assert venue.cross_provider_id == "future-aggregator-456"
    assert venue.provider_venue_id != venue.cross_provider_id
    assert venue.provenance["rating"].endpoint_id == "dineout-discovery"
    assert venue.provenance["rating"].evidence_state == EvidenceState.LIVE_VERIFIED
    assert venue.conflicts[0].values == (4.2, 4.4)


def test_venue_json_contract_has_fixed_provider_and_no_secret_fields() -> None:
    venue = VenueRecord(
        provider_venue_id="swiggy-123",
        name="Example Cafe",
        normalized_name="example cafe",
        retrieved_at=RETRIEVED_AT,
        provenance={"name": source("dineout-discovery")},
    )

    payload = venue.model_dump(mode="json")
    serialized = venue.model_dump_json().lower()

    assert payload["provider"] == "swiggy"
    for forbidden_name in (
        "password",
        "token",
        "cookie",
        "authorization",
        "secret",
        "otp",
    ):
        assert forbidden_name not in serialized


@pytest.mark.parametrize("declaration", ["provenance", "unavailable", "conflict"])
def test_venue_rejects_declarations_for_unknown_fields(declaration: str) -> None:
    kwargs: dict[str, object]
    if declaration == "provenance":
        kwargs = {"provenance": {"not_a_field": source("dineout-discovery")}}
    elif declaration == "unavailable":
        kwargs = {
            "unavailable_fields": (
                UnavailableField(field_name="not_a_field", reason="not exposed"),
            )
        }
    else:
        kwargs = {
            "conflicts": (
                FieldConflict(
                    field_name="not_a_field",
                    values=("first", "second"),
                    sources=(source("dineout-discovery"), source("dineout-details")),
                ),
            )
        }

    with pytest.raises(ValidationError, match="normalized VenueRecord field"):
        VenueRecord.model_validate(
            {
                "provider_venue_id": "swiggy-123",
                "name": "Example Cafe",
                "normalized_name": "example cafe",
                "retrieved_at": RETRIEVED_AT,
                **kwargs,
            }
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("name", "Example Cafe"), ("rating", 0.0), ("currently_available", False)],
)
def test_venue_rejects_unavailable_fields_with_concrete_values(
    field_name: str, value: object
) -> None:
    with pytest.raises(ValidationError, match="concrete value"):
        VenueRecord.model_validate(
            {
                "provider_venue_id": "swiggy-123",
                "name": "Example Cafe",
                "normalized_name": "example cafe",
                "retrieved_at": RETRIEVED_AT,
                field_name: value,
                "unavailable_fields": (
                    UnavailableField(field_name=field_name, reason="not exposed"),
                ),
            }
        )


def test_venue_rejects_duplicate_or_contradictory_declarations() -> None:
    unavailable = UnavailableField(field_name="rating", reason="not exposed")
    conflict = FieldConflict(
        field_name="rating",
        values=(4.2, 4.4),
        sources=(source("dineout-discovery"), source("dineout-details")),
    )
    base: dict[str, object] = {
        "provider_venue_id": "swiggy-123",
        "name": "Example Cafe",
        "normalized_name": "example cafe",
        "retrieved_at": RETRIEVED_AT,
    }

    with pytest.raises(ValidationError, match="duplicate unavailable"):
        VenueRecord.model_validate(
            {**base, "unavailable_fields": (unavailable, unavailable)}
        )
    with pytest.raises(ValidationError, match="duplicate conflict"):
        VenueRecord.model_validate({**base, "conflicts": (conflict, conflict)})
    with pytest.raises(ValidationError, match="both unavailable and conflicting"):
        VenueRecord.model_validate(
            {
                **base,
                "unavailable_fields": (unavailable,),
                "conflicts": (conflict,),
            }
        )
    with pytest.raises(ValidationError, match="both unavailable and sourced"):
        VenueRecord.model_validate(
            {
                **base,
                "provenance": {"rating": source("dineout-discovery")},
                "unavailable_fields": (unavailable,),
            }
        )


def test_selected_conflict_source_must_be_one_of_the_retained_sources() -> None:
    discovery = source("dineout-discovery")
    details = source("dineout-details")
    reviews = source("dineout-reviews")
    conflict = FieldConflict(
        field_name="rating",
        values=(4.2, 4.4),
        sources=(discovery, details),
    )

    with pytest.raises(ValidationError, match="selected provenance source"):
        VenueRecord(
            provider_venue_id="swiggy-123",
            name="Example Cafe",
            normalized_name="example cafe",
            rating=4.2,
            retrieved_at=RETRIEVED_AT,
            provenance={"rating": reviews},
            conflicts=(conflict,),
        )

    venue_without_selected_source = VenueRecord(
        provider_venue_id="swiggy-123",
        name="Example Cafe",
        normalized_name="example cafe",
        rating=4.2,
        retrieved_at=RETRIEVED_AT,
        conflicts=(conflict,),
    )
    assert venue_without_selected_source.conflicts == (conflict,)
    assert "rating" not in venue_without_selected_source.provenance


def test_venue_conflict_requires_a_concrete_selected_value() -> None:
    conflict = FieldConflict(
        field_name="rating",
        values=(None, 4.4),
        sources=(source("dineout-discovery"), source("dineout-details")),
    )

    with pytest.raises(ValidationError, match="concrete selected value"):
        VenueRecord(
            provider_venue_id="swiggy-123",
            name="Example Cafe",
            normalized_name="example cafe",
            retrieved_at=RETRIEVED_AT,
            conflicts=(conflict,),
        )


def test_venue_conflict_selected_value_must_be_retained() -> None:
    conflict = FieldConflict(
        field_name="rating",
        values=(4.2, 4.4),
        sources=(source("dineout-discovery"), source("dineout-details")),
    )

    with pytest.raises(ValidationError, match="retained conflict values"):
        VenueRecord(
            provider_venue_id="swiggy-123",
            name="Example Cafe",
            normalized_name="example cafe",
            rating=4.3,
            retrieved_at=RETRIEVED_AT,
            conflicts=(conflict,),
        )


def test_venue_conflict_provenance_must_match_the_selected_value_pair() -> None:
    discovery = source("dineout-discovery")
    details = source("dineout-details")
    conflict = FieldConflict(
        field_name="rating",
        values=(4.2, 4.4),
        sources=(discovery, details),
    )

    with pytest.raises(ValidationError, match="same retained candidate"):
        VenueRecord(
            provider_venue_id="swiggy-123",
            name="Example Cafe",
            normalized_name="example cafe",
            rating=4.4,
            retrieved_at=RETRIEVED_AT,
            provenance={"rating": discovery},
            conflicts=(conflict,),
        )


def test_venue_conflict_matches_model_json_with_repeated_sources() -> None:
    discovery = source("dineout-discovery")
    details = source("dineout-details")
    conflict = FieldConflict(
        field_name="coordinates",
        values=(
            {"latitude": 28.4, "longitude": 77.0},
            {"latitude": 28.6, "longitude": 77.2},
            {"longitude": 77.1, "latitude": 28.5},
        ),
        sources=(details, discovery, details),
    )

    venue = VenueRecord(
        provider_venue_id="swiggy-123",
        name="Example Cafe",
        normalized_name="example cafe",
        coordinates=Coordinates(latitude=28.5, longitude=77.1),
        retrieved_at=RETRIEVED_AT,
        provenance={"coordinates": details},
        conflicts=(conflict,),
    )

    assert venue.coordinates == Coordinates(latitude=28.5, longitude=77.1)


def test_public_exceptions_share_a_single_base_type() -> None:
    for error_type in (
        ConfigurationError,
        TransportError,
        ProviderResponseError,
        SchemaDriftError,
        UnsafeEndpointError,
    ):
        assert issubclass(error_type, SwiggyError)
