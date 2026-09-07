from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from swiggy.errors import SchemaDriftError
from swiggy.models import ReviewSample
from swiggy.provenance import EvidenceState, SourceEvidence
from swiggy.reviews import ReviewPage, parse_reviews

FIXTURES = Path(__file__).parents[1] / "fixtures" / "contracts"
RETRIEVED_AT = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def evidence() -> SourceEvidence:
    return SourceEvidence(
        endpoint_id="dineout-reviews",
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        confidence=0.9,
    )


def load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    )


def test_parse_dated_reviews_normalizes_samples_ids_and_cursor() -> None:
    page = parse_reviews(load("reviews_dated.json"), evidence())

    assert isinstance(page, ReviewPage)
    assert page.reviews == (
        ReviewSample(
            rating=4.5,
            text="Excellent food and service",
            reviewed_at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
            source=evidence(),
        ),
        ReviewSample(
            rating=3.0,
            text="Good ambience",
            reviewed_at=datetime(2026, 9, 4, 18, 30, tzinfo=UTC),
            source=evidence(),
        ),
    )
    assert page.review_ids == ("review-1", "review-2")
    assert page.next_cursor == "cursor-2"


def test_parse_undated_reviews_retains_none_without_inventing_boundary() -> None:
    page = parse_reviews(load("reviews_undated.json"), evidence())

    assert len(page.reviews) == 2
    assert all(review.reviewed_at is None for review in page.reviews)
    assert page.review_ids == ("review-3",)
    assert page.next_cursor is None


def test_parse_paginated_reviews_supports_nested_cursor_shapes() -> None:
    page = parse_reviews(load("reviews_paginated.json"), evidence())

    assert [review.rating for review in page.reviews] == [4.0]
    assert page.next_cursor == "40"


def test_malformed_review_schema_has_endpoint_and_parser_context() -> None:
    with pytest.raises(SchemaDriftError, match="dineout-reviews.*reviews"):
        parse_reviews(load("reviews_malformed.json"), evidence())


def test_review_page_is_immutable() -> None:
    page = parse_reviews({"reviews": []}, evidence())

    with pytest.raises(AttributeError):
        page.next_cursor = "changed"  # type: ignore[misc]


def test_naive_review_timestamp_is_schema_drift() -> None:
    with pytest.raises(SchemaDriftError, match="dineout-reviews.*reviews"):
        parse_reviews(
            {"reviews": [{"rating": 4, "reviewed_at": "2026-09-05T12:00:00"}]},
            evidence(),
        )
