from __future__ import annotations

from datetime import UTC, datetime

from swiggy.models import Coordinates, Offer, ReviewSample, VenueAttributes, VenueRecord
from swiggy.provenance import EvidenceState, SourceEvidence
from swiggy.ranking import RankingResult, rank_venue, rank_venues

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def evidence() -> SourceEvidence:
    return SourceEvidence(
        endpoint_id="test",
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=NOW,
        confidence=0.95,
    )


def venue(**updates: object) -> VenueRecord:
    data: dict[str, object] = {
        "provider_venue_id": "1",
        "name": "Cafe One",
        "normalized_name": "cafe one",
        "rating": 4.8,
        "rating_count": 100,
        "retrieved_at": NOW,
        "provenance": {"rating": evidence(), "rating_count": evidence()},
    }
    data.update(updates)
    return VenueRecord.model_validate(data)


def test_quality_is_bounded_and_uses_rating_volume() -> None:
    result = rank_venue(venue(), mode="top-rated", as_of=NOW)

    assert isinstance(result, RankingResult)
    assert 0 <= result.quality <= 100
    assert result.score == result.quality


def test_undated_reviews_do_not_claim_trending() -> None:
    current = venue(
        review_samples=(ReviewSample(rating=5, text="great", source=evidence()),)
    )

    result = rank_venue(current, mode="trending", as_of=NOW)

    assert result.momentum is None
    assert result.trend == "insufficient evidence"
    assert "insufficient evidence" in result.reason


def test_recent_dated_reviews_can_qualify_with_explanation() -> None:
    current = venue(
        review_samples=(
            ReviewSample(
                rating=5,
                text="great",
                reviewed_at=datetime(2026, 9, 5, tzinfo=UTC),
                source=evidence(),
            ),
            ReviewSample(
                rating=5,
                text="great",
                reviewed_at=datetime(2026, 9, 4, tzinfo=UTC),
                source=evidence(),
            ),
            ReviewSample(
                rating=5,
                text="great",
                reviewed_at=datetime(2026, 7, 1, tzinfo=UTC),
                source=evidence(),
            ),
        )
    )

    result = rank_venue(current, mode="trending", as_of=NOW)

    assert result.momentum is not None
    assert result.trend == "trending"
    assert "dated" in result.reason


def test_expired_offers_contribute_zero() -> None:
    expired = Offer(
        title="Expired",
        discount_percent=80,
        valid_until=datetime(2026, 9, 1, tzinfo=UTC).date(),
        source=evidence(),
    )

    result = rank_venue(venue(offers=(expired,)), mode="offers", as_of=NOW)

    assert result.offer_strength == 0


def test_nightlife_uses_explicit_attributes_only() -> None:
    result = rank_venue(
        venue(attributes=VenueAttributes(bar=True, late_night=True)),
        mode="nightlife",
        as_of=NOW,
    )

    assert result.score > 0
    assert "explicit" in result.reason


def test_distance_is_retained_separately() -> None:
    result = rank_venue(
        venue(coordinates=Coordinates(latitude=28.5, longitude=77.1)),
        mode="top-rated",
        origin=Coordinates(latitude=28.51, longitude=77.1),
        as_of=NOW,
    )

    assert result.distance_km is not None
    assert result.distance_km > 0


def test_tie_breaking_is_deterministic() -> None:
    first = venue(provider_venue_id="2", name="Beta", normalized_name="beta")
    second = venue(provider_venue_id="1", name="Alpha", normalized_name="alpha")

    ranked = rank_venues([first, second], mode="top-rated", as_of=NOW)

    assert [item.venue.provider_venue_id for item in ranked] == ["1", "2"]
