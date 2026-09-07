from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from swiggy.discovery import DiscoveryPage, DiscoveryService, parse_discovery_page
from swiggy.errors import ProviderResponseError, SchemaDriftError
from swiggy.provenance import EvidenceState, SourceEvidence
from swiggy.transport import TransportResponse

FIXTURES = Path(__file__).parents[1] / "fixtures" / "contracts"
RETRIEVED_AT = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def evidence() -> SourceEvidence:
    return SourceEvidence(
        endpoint_id="dineout-discovery",
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        confidence=0.95,
    )


def load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    )


def test_parse_valid_page_normalizes_cards_and_cursor() -> None:
    page = parse_discovery_page(load("discovery_page_1.json"), evidence())

    assert isinstance(page, DiscoveryPage)
    assert [venue.provider_venue_id for venue in page.venues] == ["302252", "844896"]
    assert page.venues[0].name == "Farzi Cafe"
    assert page.venues[0].normalized_name == "farzi cafe"
    assert page.venues[0].cuisines == ("Modern Indian", "Continental")
    assert page.next_cursor == "20"
    assert page.venues[0].provenance["rating"] == evidence()
    assert page.venues[0].provenance["provider_venue_id"] == evidence()


def test_parse_legitimate_empty_page_is_not_an_error() -> None:
    page = parse_discovery_page(load("discovery_empty.json"), evidence())

    assert page.venues == ()
    assert page.next_cursor is None


def test_provider_error_card_is_distinct_from_empty_success() -> None:
    with pytest.raises(ProviderResponseError, match="dineout-discovery"):
        parse_discovery_page(load("discovery_error.json"), evidence())


def test_malformed_schema_has_endpoint_and_parser_context() -> None:
    with pytest.raises(SchemaDriftError, match="dineout-discovery.*discovery"):
        parse_discovery_page({"cards": [{"name": "missing id"}]}, evidence())


def test_missing_optional_fields_are_explicitly_unavailable() -> None:
    page = parse_discovery_page(load("discovery_page_2.json"), evidence())
    venue = page.venues[0]

    assert venue.rating == 3.0
    assert venue.cost_for_two is None
    assert venue.locality == "Connaught Place, Delhi"
    assert venue.coordinates is not None
    assert venue.coordinates.latitude == 28.5
    assert venue.provenance["coordinates"] == evidence()
    unavailable = {item.field_name: item for item in venue.unavailable_fields}
    assert unavailable["cost_for_two"].reason == "not present in discovery response"
    assert unavailable["cuisines"].sources == (evidence(),)


def test_offset_and_cursor_shapes_are_extracted_as_strings() -> None:
    cases: list[tuple[dict[str, object], str]] = [
        ({"cards": [], "next_offset": 20}, "20"),
        ({"cards": [], "pagination": {"nextCursor": "abc"}}, "abc"),
        ({"cards": [], "page_offset": {"next_offset": "40"}}, "40"),
    ]
    for payload, expected in cases:
        page = parse_discovery_page(payload, evidence())
        assert page.next_cursor == expected


def test_service_deduplicates_by_stable_id_and_merges_richer_later_fields() -> None:
    responses = [
        load("discovery_page_1.json"),
        load("discovery_page_2.json"),
    ]

    class FakeTransport:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, endpoint_id: str, **_: object) -> TransportResponse:
            assert endpoint_id == "dineout-discovery"
            payload = responses[self.calls]
            self.calls += 1
            return TransportResponse(
                endpoint_id=endpoint_id,
                status_code=200,
                headers={},
                text=json.dumps(payload),
                json_payload=payload,
            )

    transport = FakeTransport()
    venues = DiscoveryService(transport).nearby(max_pages=2)

    assert [venue.provider_venue_id for venue in venues] == [
        "302252",
        "844896",
        "991122",
    ]
    farzi = venues[0]
    assert farzi.cost_for_two == 2000
    assert farzi.rating == 4.0
    assert farzi.provenance["cost_for_two"].endpoint_id == "dineout-discovery"
    assert transport.calls == 2


def test_service_stops_on_repeated_cursor_and_maximums() -> None:
    page = {"cards": [{"provider_venue_id": "1", "name": "One"}], "next_offset": "x"}

    class FakeTransport:
        calls = 0

        def request(self, endpoint_id: str, **_: object) -> TransportResponse:
            self.calls += 1
            return TransportResponse(
                endpoint_id=endpoint_id,
                status_code=200,
                headers={},
                text=json.dumps(page),
                json_payload=page,
            )

    transport = FakeTransport()
    venues = DiscoveryService(transport).nearby(max_pages=10, max_results=1)

    assert len(venues) == 1
    assert transport.calls == 1

    transport = FakeTransport()
    venues = DiscoveryService(transport).nearby(max_pages=3, max_results=10)
    assert len(venues) == 1
    assert transport.calls == 2


def test_service_accepts_json_text_response_without_persisting_payload() -> None:
    payload = load("discovery_empty.json")

    class FakeTransport:
        def request(self, endpoint_id: str, **_: object) -> TransportResponse:
            return TransportResponse(
                endpoint_id=endpoint_id,
                status_code=200,
                headers={"content-type": "application/json"},
                text=json.dumps(payload),
                json_payload=None,
            )

    assert DiscoveryService(FakeTransport()).nearby() == ()


def test_boolean_provider_id_is_schema_drift() -> None:
    with pytest.raises(SchemaDriftError, match="dineout-discovery.*discovery"):
        parse_discovery_page(
            {"cards": [{"provider_venue_id": False, "name": "Invalid"}]},
            evidence(),
        )


def test_empty_transport_text_is_schema_drift() -> None:
    class FakeTransport:
        def request(self, endpoint_id: str, **_: object) -> TransportResponse:
            return TransportResponse(
                endpoint_id=endpoint_id,
                status_code=200,
                headers={},
                text="",
                json_payload=None,
            )

    with pytest.raises(SchemaDriftError, match="dineout-discovery.*discovery"):
        DiscoveryService(FakeTransport()).nearby()
