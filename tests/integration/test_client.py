from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from swiggy.client import SwiggyClient
from swiggy.errors import ConfigurationError
from swiggy.models import VenueRecord
from swiggy.transport import TransportResponse


class FixtureTransport:
    def __init__(self, *, fail_ids: set[str] | None = None) -> None:
        self.fail_ids = fail_ids or set()
        self.calls: list[tuple[str, Mapping[str, object]]] = []
        self.closed = False

    def request(self, endpoint_id: str, **kwargs: object) -> TransportResponse:
        self.calls.append((endpoint_id, kwargs))
        if endpoint_id == "dineout-discovery":
            payload: object = {
                "cards": [
                    {
                        "provider_venue_id": "2",
                        "name": "Second Cafe",
                        "locality": "Hauz Khas, Delhi",
                        "rating": 3.5,
                    },
                    {
                        "provider_venue_id": "1",
                        "name": "First Cafe",
                        "locality": "Connaught Place, Delhi",
                        "rating": 4.0,
                    },
                ]
            }
        else:
            path_params = kwargs.get("path_params")
            assert isinstance(path_params, Mapping)
            venue_id = {"first-cafe": "1", "second-cafe": "2"}[str(path_params["name"])]
            if venue_id in self.fail_ids:
                raise RuntimeError("synthetic provider failure")
            payload = {
                "provider_venue_id": venue_id,
                "name": "First Cafe" if venue_id == "1" else "Second Cafe",
                "cost_for_two": 1500,
                "amenities": ["Bar", "Parking available"],
                "menu_sections": [{"label": "Dinner", "id": "menu-1"}],
                "offers": [{"title": "20% off", "discount_percent": 20}],
            }
        return TransportResponse(
            endpoint_id=endpoint_id,
            status_code=200,
            headers={"content-type": "application/json"},
            text=json.dumps(payload),
            json_payload=payload,
        )

    def close(self) -> None:
        self.closed = True


class ReviewlessClient(SwiggyClient):
    def get_reviews(self, venue_id: str, limit: int = 30) -> tuple[object, ...]:
        return ()


def test_guest_search_detail_and_detail_derived_offers() -> None:
    transport = FixtureTransport()
    client = SwiggyClient(transport=transport)

    venues = client.search_nearby(max_results=2)
    detail = client.get_restaurant("1")
    offers = client.get_offers("1")

    assert [venue.provider_venue_id for venue in venues] == ["2", "1"]
    assert detail.provider_venue_id == "1"
    assert detail.menu_references[0].provider_menu_id == "menu-1"
    assert offers[0].title == "20% off"
    detail_call = transport.calls[1]
    assert detail_call[0] == "dineout-restaurant-detail"
    assert detail_call[1]["path_params"] == {
        "city": "delhi",
        "area": "connaught-place",
        "name": "first-cafe",
    }


def test_enrichment_preserves_input_order_and_records_partial_failures() -> None:
    transport = FixtureTransport(fail_ids={"2"})
    client = ReviewlessClient(transport=transport)
    venues = client.search_nearby()

    enriched = client.enrich(venues, max_workers=2)

    assert [venue.provider_venue_id for venue in enriched] == ["2", "1"]
    assert enriched[0] == venues[0]
    assert enriched[1].cost_for_two == 1500
    assert enriched[1].offers[0].title == "20% off"
    assert [failure.provider_venue_id for failure in client.enrichment_failures] == [
        "2"
    ]
    assert client.enrichment_failures[0].stage == "detail"


def test_enrichment_rejects_unbounded_worker_configuration() -> None:
    client = SwiggyClient(transport=FixtureTransport())
    venue = VenueRecord(
        provider_venue_id="1",
        name="First Cafe",
        normalized_name="first cafe",
        retrieved_at=datetime(2026, 9, 7, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="max_workers"):
        client.enrich((venue,), max_workers=0)


def test_client_closes_injected_transport_but_transport_owns_httpx_client() -> None:
    transport = FixtureTransport()
    client = SwiggyClient(transport=transport)

    client.close()

    assert transport.closed is True


def test_enrichment_fetches_detail_once_per_venue_and_orders_failures() -> None:
    transport = FixtureTransport(fail_ids={"1", "2"})
    client = SwiggyClient(transport=transport)
    venues = client.search_nearby()

    enriched = client.enrich(venues, max_workers=2)

    assert enriched == venues
    assert [failure.provider_venue_id for failure in client.enrichment_failures] == [
        "2",
        "1",
    ]
    assert [endpoint for endpoint, _ in transport.calls].count(
        "dineout-restaurant-detail"
    ) == 2


def test_detail_failure_does_not_skip_offer_enrichment() -> None:
    class MalformedDetailTransport(FixtureTransport):
        def request(self, endpoint_id: str, **kwargs: object) -> TransportResponse:
            if endpoint_id == "dineout-discovery":
                return super().request(endpoint_id, **kwargs)
            payload = {"offers": [{"title": "20% off", "discount_percent": 20}]}
            return TransportResponse(
                endpoint_id=endpoint_id,
                status_code=200,
                headers={"content-type": "application/json"},
                text=json.dumps(payload),
                json_payload=payload,
            )

    client = SwiggyClient(transport=MalformedDetailTransport())
    venue = client.search_nearby(max_results=1)[0]

    enriched = client.enrich((venue,))

    assert enriched[0].offers[0].title == "20% off"
    assert [failure.stage for failure in client.enrichment_failures] == ["detail"]


def test_network_detail_failure_still_attempts_reviews() -> None:
    class ReviewTrackingClient(SwiggyClient):
        def __init__(self, transport: FixtureTransport) -> None:
            super().__init__(transport)
            self.review_calls: list[str] = []

        def get_reviews(self, venue_id: str, limit: int = 30) -> tuple[object, ...]:
            del limit
            self.review_calls.append(venue_id)
            return ()

    transport = FixtureTransport(fail_ids={"1"})
    client = ReviewTrackingClient(transport)
    venue = client.search_nearby()[1]

    result = client.enrich((venue,))

    assert result == (venue,)
    assert client.review_calls == ["1"]
    assert [failure.stage for failure in client.enrichment_failures] == ["detail"]


def test_unknown_venue_route_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="search nearby"):
        SwiggyClient(transport=FixtureTransport()).get_restaurant("missing")
