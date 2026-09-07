"""Deterministic, evidence-aware ranking for normalized venues."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from swiggy.models import Coordinates, VenueRecord

PRIOR_RATING = 3.5
PRIOR_COUNT = 10
RECENT_WINDOW = timedelta(days=30)
OLDER_WINDOW = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class RankingResult:
    venue: VenueRecord
    mode: str
    score: float
    quality: float
    momentum: float | None
    freshness: float | None
    offer_strength: float
    confidence: float
    distance_km: float | None
    trend: str
    reason: str
    evidence: tuple[str, ...]


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _quality(venue: VenueRecord) -> tuple[float, str]:
    if venue.rating is None:
        return 0.0, "rating unavailable"
    count = max(0, venue.rating_count or 0)
    posterior = (venue.rating * count + PRIOR_RATING * PRIOR_COUNT) / (
        count + PRIOR_COUNT
    )
    volume_factor = 0.6 + 0.4 * min(1.0, math.log1p(count) / math.log1p(1000))
    return _bounded(posterior / 5.0 * 100.0 * volume_factor), (
        f"rating {venue.rating:.1f} with {count} ratings and a "
        f"{PRIOR_RATING:.1f}/{PRIOR_COUNT} Bayesian prior"
    )


def _momentum(venue: VenueRecord, as_of: datetime) -> tuple[float | None, str]:
    dated = [
        sample.reviewed_at
        for sample in venue.review_samples
        if sample.reviewed_at is not None
    ]
    if not dated:
        return None, "insufficient evidence: reviews have no timestamps"
    recent_start = as_of - RECENT_WINDOW
    older_start = as_of - OLDER_WINDOW
    recent = sum(retrieved >= recent_start for retrieved in dated)
    older = sum(older_start <= retrieved < recent_start for retrieved in dated)
    if recent == 0 and older == 0:
        return None, "insufficient evidence: no dated reviews in comparison windows"
    if older == 0:
        return None, "insufficient evidence: no older dated review baseline"
    rate_ratio = recent / max(1, older)
    score = _bounded(50.0 * min(2.0, rate_ratio))
    trend = "trending" if recent > older and recent > 0 else "stable"
    return score, (
        f"{trend}: {recent} dated review(s) in the recent window versus "
        f"{older} in the older comparison window"
    )


def _offer_strength(venue: VenueRecord, as_of: datetime) -> tuple[float, str]:
    active = [
        offer
        for offer in venue.offers
        if offer.valid_until is None or offer.valid_until >= as_of.date()
    ]
    if not active:
        return 0.0, "no active offers; expired offers contribute zero"
    discounts = [offer.discount_percent or 0.0 for offer in active]
    strongest = _bounded(max(discounts, default=0.0))
    return strongest, f"strongest active stated discount is {strongest:.1f}%"


def _freshness(venue: VenueRecord) -> tuple[float | None, str]:
    facilities = venue.attributes.facilities if venue.attributes else ()
    explicit = [
        item
        for item in facilities
        if re.search(r"\b(new|listed|updated|campaign)\b", item, re.I)
    ]
    if not explicit:
        return None, "insufficient evidence: no explicit freshness signal"
    return 80.0, f"explicit freshness signal: {explicit[0]}"


def _distance(origin: Coordinates | None, venue: VenueRecord) -> float | None:
    if origin is None or venue.coordinates is None:
        return None
    radius = 6371.0088
    lat1, lat2 = math.radians(origin.latitude), math.radians(venue.coordinates.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(venue.coordinates.longitude - origin.longitude)
    a = math.sin(dlat / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.asin(math.sqrt(a))


def _nightlife(venue: VenueRecord) -> tuple[float, str]:
    attributes = venue.attributes
    if attributes is None:
        return 0.0, "insufficient evidence: no explicit nightlife attributes"
    flags = [
        attributes.bar,
        attributes.live_music,
        attributes.rooftop,
        attributes.dance_floor,
        attributes.late_night,
    ]
    score = _bounded(sum(flag is True for flag in flags) / len(flags) * 100.0)
    return score, "nightlife score uses explicit provider-declared attributes only"


def rank_venue(
    venue: VenueRecord,
    *,
    mode: str = "top-rated",
    origin: Coordinates | None = None,
    as_of: datetime | None = None,
) -> RankingResult:
    """Score one venue without inventing unavailable evidence."""

    now = as_of or datetime.now(UTC)
    quality, quality_reason = _quality(venue)
    momentum, momentum_reason = _momentum(venue, now)
    freshness, freshness_reason = _freshness(venue)
    offer_strength, offer_reason = _offer_strength(venue, now)
    distance = _distance(origin, venue)
    completeness = sum(
        value is not None
        for value in (
            venue.rating,
            venue.rating_count,
            venue.locality,
            venue.coordinates,
        )
    )
    confidence = _bounded(completeness / 4.0 * 100.0)
    reasons = [quality_reason, momentum_reason, freshness_reason, offer_reason]
    if mode == "top-rated":
        score = quality
    elif mode == "trending":
        score = momentum or 0.0
    elif mode == "new":
        score = freshness or 0.0
    elif mode == "offers":
        score = offer_strength
    elif mode == "nightlife":
        score, nightlife_reason = _nightlife(venue)
        reasons.append(nightlife_reason)
    else:
        raise ValueError(f"unsupported ranking mode: {mode}")
    if mode == "trending" and momentum is None:
        trend = "insufficient evidence"
    elif mode == "trending" and momentum is not None and momentum < 50:
        trend = "stable"
    elif mode == "trending":
        trend = "trending"
    else:
        trend = "not evaluated"
    return RankingResult(
        venue=venue,
        mode=mode,
        score=_bounded(score),
        quality=quality,
        momentum=momentum,
        freshness=freshness,
        offer_strength=offer_strength,
        confidence=confidence,
        distance_km=distance,
        trend=trend,
        reason="; ".join(reasons),
        evidence=tuple(reasons),
    )


def rank_venues(
    venues: Iterable[VenueRecord],
    *,
    mode: str = "top-rated",
    origin: Coordinates | None = None,
    as_of: datetime | None = None,
    limit: int | None = None,
) -> tuple[RankingResult, ...]:
    """Rank venues with deterministic tie-breaking."""

    results = [
        rank_venue(venue, mode=mode, origin=origin, as_of=as_of) for venue in venues
    ]
    results.sort(
        key=lambda item: (
            -item.score,
            -item.confidence,
            item.distance_km if item.distance_km is not None else math.inf,
            item.venue.normalized_name,
            item.venue.provider_venue_id,
        )
    )
    return tuple(results if limit is None else results[:limit])


__all__ = ["RankingResult", "rank_venue", "rank_venues"]
