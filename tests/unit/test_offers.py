from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from swiggy.errors import SchemaDriftError
from swiggy.models import Offer
from swiggy.offers import parse_offers
from swiggy.provenance import EvidenceState, SourceEvidence

FIXTURES = Path(__file__).parents[1] / "fixtures" / "contracts"
RETRIEVED_AT = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)


def evidence() -> SourceEvidence:
    return SourceEvidence(
        endpoint_id="dineout-offers",
        evidence_state=EvidenceState.LIVE_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        confidence=0.95,
    )


def load(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    )


def test_parse_structured_percentage_and_flat_offers_with_terms() -> None:
    offers = parse_offers(load("offers_structured.json"), evidence())

    assert len(offers) == 2
    percentage, flat = offers
    assert isinstance(percentage, Offer)
    assert percentage.title == "Pre-booking discount"
    assert percentage.discount_percent == 20
    assert percentage.minimum_bill == 1000
    assert percentage.valid_from is not None
    assert percentage.valid_from.isoformat() == "2026-09-01"
    assert percentage.valid_until is not None
    assert percentage.valid_until.isoformat() == "2026-09-30"
    assert percentage.description is not None
    assert "₹300" in percentage.description
    assert "Minimum bill: ₹1000" in percentage.description
    assert "18:00-23:00" in percentage.description
    assert "DO NOT RETAIN" not in percentage.description
    assert "HDFC Credit Card" in percentage.restrictions
    assert "UPI" in percentage.restrictions
    assert "Cash" in percentage.restrictions
    assert "One offer per table" in percentage.restrictions
    assert "Code: DINE20" in percentage.restrictions
    assert percentage.source == evidence()

    assert flat.title == "Flat saving"
    assert flat.discount_percent is None
    assert flat.minimum_bill == 500
    assert flat.valid_from is not None
    assert flat.valid_until is not None
    assert flat.description is not None
    assert "₹100" in flat.description
    assert "SwiggyPay" in flat.restrictions


def test_text_only_offers_retain_provider_text() -> None:
    offers = parse_offers(load("offers_text_only.json"), evidence())

    assert [offer.title for offer in offers] == [
        "Flat 25% off on pre-booking. Valid till 30 September 2026.",
        "Show this offer at the restaurant",
    ]
    assert offers[0].description == offers[0].title
    assert offers[0].discount_percent == 25
    assert offers[1].description == offers[1].title


def test_expired_disabled_and_excluded_offers_are_omitted() -> None:
    offers = parse_offers(load("offers_expired_excluded.json"), evidence())

    assert [offer.title for offer in offers] == ["Still available"]


def test_malformed_offer_schema_includes_context_without_payload() -> None:
    with pytest.raises(SchemaDriftError, match="dineout-offers.*offers") as error:
        parse_offers(
            {"offers": [{"title": "Broken", "discount_percent": "secret-token"}]},
            evidence(),
        )

    assert "secret-token" not in str(error.value)


def test_non_object_payload_is_schema_drift() -> None:
    with pytest.raises(SchemaDriftError, match="dineout-offers.*offers"):
        parse_offers(cast(Any, []), evidence())


def test_text_date_range_parses_sept_and_uses_end_date() -> None:
    offers = parse_offers(
        {"offers": [{"text": "Valid from 14 Sept 2026 to 20 Sept 2026"}]},
        evidence(),
    )

    assert offers[0].valid_from == date(2026, 9, 14)
    assert offers[0].valid_until == date(2026, 9, 20)
