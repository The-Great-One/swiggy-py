"""Stable facade coordinating discovery and isolated enrichment parsers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Protocol

from swiggy.discovery import DiscoveryService
from swiggy.errors import ConfigurationError
from swiggy.models import EnrichmentFailure, VenueRecord
from swiggy.offers import parse_offers
from swiggy.provenance import EvidenceState, SourceEvidence
from swiggy.ranking import rank_venues
from swiggy.restaurants import RestaurantDetail, parse_restaurant_detail
from swiggy.transport import TransportResponse


class ClientTransport(Protocol):
    def request(self, endpoint_id: str, **kwargs: object) -> TransportResponse: ...

    def close(self) -> None: ...


class Ranker(Protocol):
    def rank(
        self,
        venues: Iterable[VenueRecord],
        *,
        mode: str,
        radius_km: float | None,
        limit: int,
    ) -> tuple[VenueRecord, ...]: ...


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _evidence(response: TransportResponse) -> SourceEvidence:
    return SourceEvidence(
        endpoint_id=response.endpoint_id,
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=datetime.now(UTC),
        confidence=0.9,
    )


def _payload(response: TransportResponse) -> Mapping[str, object]:
    if isinstance(response.json_payload, Mapping):
        return response.json_payload
    import json

    value = json.loads(response.text or "")
    if not isinstance(value, Mapping):
        raise ValueError("provider response was not an object")
    return value


def _merge_detail(venue: VenueRecord, detail: RestaurantDetail) -> VenueRecord:
    data = {
        field_name: getattr(venue, field_name)
        for field_name in VenueRecord.model_fields
    }
    provenance = dict(venue.provenance)
    unavailable = {item.field_name: item for item in venue.unavailable_fields}
    for field_name in RestaurantDetail.model_fields:
        if field_name in {
            "provider_venue_id",
            "retrieved_at",
            "provenance",
            "unavailable_fields",
        }:
            continue
        value = getattr(detail, field_name)
        if value is not None and value != ():
            data[field_name] = value
            if field_name in detail.provenance:
                provenance[field_name] = detail.provenance[field_name]
            unavailable.pop(field_name, None)
    data["provenance"] = provenance
    data["unavailable_fields"] = tuple(unavailable.values())
    return VenueRecord.model_validate(data)


class SwiggyClient:
    """Provider facade with guest-first discovery and bounded enrichment."""

    def __init__(
        self,
        transport: ClientTransport,
        *,
        ranker: Ranker | Callable[..., tuple[VenueRecord, ...]] | None = None,
    ) -> None:
        self.transport = transport
        self.discovery = DiscoveryService(transport)
        self.ranker = ranker
        self._venues: dict[str, VenueRecord] = {}
        self._enrichment_failures: list[EnrichmentFailure] = []
        self._closed = False

    @property
    def enrichment_failures(self) -> tuple[EnrichmentFailure, ...]:
        return tuple(self._enrichment_failures)

    def search_nearby(
        self, *, max_pages: int = 10, max_results: int = 100
    ) -> tuple[VenueRecord, ...]:
        venues = self.discovery.nearby(max_pages=max_pages, max_results=max_results)
        self._venues.update({venue.provider_venue_id: venue for venue in venues})
        return venues

    def _path_params(self, venue_id: str) -> dict[str, str]:
        venue = self._venues.get(venue_id)
        if venue is None:
            raise ConfigurationError(
                "Venue route is unavailable; search nearby before requesting details"
            )
        if venue.locality is None:
            raise ConfigurationError(
                "Venue route is unavailable; provider locality is missing"
            )
        parts = [part.strip() for part in venue.locality.split(",")]
        if len(parts) < 2 or not all(parts):
            raise ConfigurationError(
                "Venue route is unavailable; provider locality is incomplete"
            )
        area = parts[0]
        city = parts[-1]
        return {"city": _slug(city), "area": _slug(area), "name": _slug(venue.name)}

    def _detail_response(self, venue_id: str) -> TransportResponse:
        return self.transport.request(
            "dineout-restaurant-detail", path_params=self._path_params(venue_id)
        )

    def get_restaurant(self, venue_id: str) -> VenueRecord:
        response = self._detail_response(venue_id)
        return self._parse_restaurant_response(venue_id, response)

    def _parse_restaurant_response(
        self, venue_id: str, response: TransportResponse
    ) -> VenueRecord:
        detail = parse_restaurant_detail(_payload(response), _evidence(response))
        base = self._venues[venue_id]
        result = _merge_detail(base, detail)
        self._venues[venue_id] = result
        return result

    def get_offers(self, venue_id: str) -> tuple[Any, ...]:
        response = self._detail_response(venue_id)
        return parse_offers(_payload(response), _evidence(response))

    def get_reviews(self, venue_id: str, limit: int = 30) -> tuple[Any, ...]:
        del venue_id, limit
        return ()

    def _failure(
        self,
        venue_id: str,
        stage: str,
        error: Exception,
        endpoint_id: str | None,
    ) -> EnrichmentFailure:
        return EnrichmentFailure(
            provider_venue_id=venue_id,
            stage=stage,
            reason=type(error).__name__,
            endpoint_id=endpoint_id,
            retryable=False,
            retrieved_at=datetime.now(UTC),
        )

    def _enrich_one(
        self, venue: VenueRecord
    ) -> tuple[VenueRecord, tuple[EnrichmentFailure, ...]]:
        venue_id = venue.provider_venue_id
        failures: list[EnrichmentFailure] = []
        result = venue
        response: TransportResponse | None = None
        try:
            response = self._detail_response(venue_id)
        except Exception as error:
            failures.append(
                self._failure(venue_id, "detail", error, "dineout-restaurant-detail")
            )

        if response is not None:
            try:
                detail = parse_restaurant_detail(
                    _payload(response), _evidence(response)
                )
                result = _merge_detail(result, detail)
            except Exception as error:
                failures.append(
                    self._failure(venue_id, "detail", error, response.endpoint_id)
                )

            try:
                offers = parse_offers(_payload(response), _evidence(response))
                result = result.model_copy(update={"offers": offers})
            except Exception as error:
                failures.append(
                    self._failure(venue_id, "offers", error, response.endpoint_id)
                )

        try:
            reviews = self.get_reviews(venue_id)
            if reviews:
                result = result.model_copy(update={"review_samples": reviews})
        except Exception as error:
            failures.append(self._failure(venue_id, "reviews", error, None))
        return result, tuple(failures)

    def enrich(
        self, venues: Iterable[VenueRecord], *, max_workers: int = 4
    ) -> tuple[VenueRecord, ...]:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        ordered = tuple(venues)
        self._enrichment_failures.clear()
        results: list[tuple[VenueRecord, tuple[EnrichmentFailure, ...]] | None] = [
            None
        ] * len(ordered)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._enrich_one, venue): index
                for index, venue in enumerate(ordered)
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        output: list[VenueRecord] = []
        for venue, failures in (item for item in results if item is not None):
            output.append(venue)
            self._enrichment_failures.extend(failures)
            self._venues[venue.provider_venue_id] = venue
        return tuple(output)

    def rank_nearby(
        self,
        mode: str,
        *,
        radius_km: float | None = None,
        limit: int = 100,
        max_workers: int = 4,
    ) -> tuple[VenueRecord, ...]:
        venues = self.enrich(
            self.search_nearby(max_results=limit), max_workers=max_workers
        )
        if self.ranker is not None:
            if callable(self.ranker):
                return self.ranker(venues, mode=mode, radius_km=radius_km, limit=limit)
            return self.ranker.rank(venues, mode=mode, radius_km=radius_km, limit=limit)
        ranked = rank_venues(
            venues,
            mode=mode,
            limit=limit,
        )
        return tuple(item.venue for item in ranked)

    def close(self) -> None:
        if not self._closed:
            self.transport.close()
            self._closed = True

    def __enter__(self) -> SwiggyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["SwiggyClient"]
