from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from swiggy.errors import SchemaDriftError
from swiggy.provenance import EvidenceState, SourceEvidence
from swiggy.restaurants import RestaurantDetail, parse_restaurant_detail

FIXTURES = Path(__file__).parents[1] / "fixtures" / "contracts"
RETRIEVED_AT = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def evidence() -> SourceEvidence:
    return SourceEvidence(
        endpoint_id="dineout-restaurant-detail",
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        confidence=0.95,
    )


def load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    )


def test_parse_detail_normalizes_structured_fields_and_provenance() -> None:
    detail = parse_restaurant_detail(load("detail_enrichment.json"), evidence())

    assert isinstance(detail, RestaurantDetail)
    assert detail.provider_venue_id == "302252"
    assert detail.name == "Farzi Cafe"
    assert detail.coordinates is not None
    assert detail.coordinates.latitude == 28.6328
    assert detail.display_address == "E-11, Inner Circle, Connaught Place"
    assert detail.cuisines == ("Modern Indian", "Continental")
    assert detail.cost_for_two == 2000
    assert detail.rating == 4.0
    assert detail.rating_count == 1250
    opens_at = detail.operating_hours[0].opens_at
    closes_at = detail.operating_hours[0].closes_at
    assert opens_at is not None
    assert closes_at is not None
    assert opens_at.isoformat() == "11:00:00"
    assert closes_at.isoformat() == "23:30:00"
    assert detail.menu_references[0].label == "Food"
    assert detail.menu_references[0].provider_menu_id == "food-1"
    assert detail.attributes is not None
    assert detail.attributes.bar is True
    assert detail.attributes.live_music is True
    assert detail.attributes.facilities == (
        "Parking available",
        "Reservation available",
    )
    assert detail.provenance["coordinates"] == evidence()
    assert detail.provenance["menu_references"] == evidence()
    assert detail.unavailable_fields == ()


def test_presentation_labels_are_not_guessed_as_attributes_or_hours() -> None:
    detail = parse_restaurant_detail(load("restaurant_detail_302252.json"), evidence())

    assert detail.operating_hours == ()
    assert detail.attributes is not None
    assert detail.attributes.late_night is None
    assert detail.attributes.bar is True
    assert detail.attributes.facilities == (
        "Jain food",
        "Reservation available",
        "Parking available",
        "Free wifi",
        "Smoking area",
        "SwiggyPay accepted",
    )
    assert "operating_hours" in {item.field_name for item in detail.unavailable_fields}


def test_missing_detail_fields_are_explicitly_unavailable() -> None:
    detail = parse_restaurant_detail(
        {"provider_venue_id": "1", "name": "Sparse"}, evidence()
    )

    unavailable = {item.field_name: item for item in detail.unavailable_fields}
    assert set(unavailable) == {
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
    }
    assert unavailable["rating"].reason == "not present in restaurant detail response"
    assert unavailable["rating"].sources == (evidence(),)


def test_schema_drift_has_endpoint_and_parser_context_without_payload_data() -> None:
    with pytest.raises(
        SchemaDriftError, match="dineout-restaurant-detail.*restaurant detail"
    ) as exc:
        parse_restaurant_detail(
            {"provider_venue_id": "1", "name": "x", "rating": "secret-token"},
            evidence(),
        )

    assert "secret-token" not in str(exc.value)


def test_numeric_text_does_not_keep_currency_prefix_period() -> None:
    detail = parse_restaurant_detail(
        {"provider_venue_id": "1", "name": "Cafe", "cost_for_two": "Rs. 500"},
        evidence(),
    )

    assert detail.cost_for_two == 500.0


def test_invalid_normalized_detail_is_wrapped_with_context() -> None:
    with pytest.raises(
        SchemaDriftError, match="dineout-restaurant-detail.*restaurant detail"
    ):
        parse_restaurant_detail(
            {"provider_venue_id": "1", "name": "Cafe", "rating": -1},
            evidence(),
        )


def test_detail_result_is_immutable() -> None:
    detail = parse_restaurant_detail(
        {"provider_venue_id": "1", "name": "Immutable"}, evidence()
    )

    with pytest.raises((TypeError, AttributeError, ValueError)):
        detail.name = "changed"
