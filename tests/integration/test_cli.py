from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import swiggy.cli as cli
from swiggy.models import Offer, ReviewSample, VenueRecord
from swiggy.provenance import EvidenceState, SourceEvidence

runner = CliRunner()


EVIDENCE = SourceEvidence(
    endpoint_id="fixture",
    evidence_state=EvidenceState.LIVE_VERIFIED,
    retrieved_at=datetime(2026, 9, 7, tzinfo=UTC),
    confidence=0.9,
)


def venue(venue_id: str = "1") -> VenueRecord:
    return VenueRecord(
        provider_venue_id=venue_id,
        name="First Cafe",
        normalized_name="first cafe",
        locality="Sector 29, Gurugram",
        rating=4.5,
        rating_count=120,
        retrieved_at=EVIDENCE.retrieved_at,
        provenance={
            "provider_venue_id": EVIDENCE,
            "name": EVIDENCE,
            "normalized_name": EVIDENCE,
            "locality": EVIDENCE,
            "rating": EVIDENCE,
            "rating_count": EVIDENCE,
        },
    )


class FixtureClient:
    def __init__(self) -> None:
        self.enrichment_failures = ()
        self.closed = False
        self.calls: list[tuple[str, object]] = []

    def search_nearby(
        self,
        *,
        max_pages: int = 10,
        max_results: int = 100,
        radius_km: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> tuple[VenueRecord, ...]:
        self.calls.append(("search", (max_pages, max_results)))
        return (venue(),)

    def enrich(
        self, venues: Iterable[VenueRecord], *, max_workers: int = 4
    ) -> tuple[VenueRecord, ...]:
        self.calls.append(("enrich", max_workers))
        return tuple(venues)

    def get_restaurant(self, venue_id: str) -> VenueRecord:
        self.calls.append(("restaurant", venue_id))
        return venue(venue_id)

    def get_offers(self, venue_id: str) -> tuple[Offer, ...]:
        self.calls.append(("offers", venue_id))
        return (Offer(title="20% off", discount_percent=20, source=EVIDENCE),)

    def get_reviews(self, venue_id: str, limit: int = 30) -> tuple[ReviewSample, ...]:
        self.calls.append(("reviews", (venue_id, limit)))
        return (ReviewSample(rating=4.0, text="Good", source=EVIDENCE),)

    def rank_nearby(
        self,
        mode: str,
        *,
        radius_km: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        limit: int = 100,
        max_workers: int = 4,
    ) -> tuple[VenueRecord, ...]:
        self.calls.append(("rank", (mode, radius_km, limit, max_workers)))
        return (venue(),)

    def close(self) -> None:
        self.closed = True


def test_restaurants_json_has_versioned_envelope_and_stable_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FixtureClient()
    monkeypatch.setattr(cli, "get_client", lambda: client)

    result = runner.invoke(
        cli.app,
        [
            "restaurants",
            "--radius",
            "15",
            "--latitude",
            "28",
            "--longitude",
            "77",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == json.loads(
        Path("tests/fixtures/cli_expected/restaurants.json").read_text()
    ) | {"results": payload["results"]}
    assert list(payload) == ["schema_version", "query", "results", "partial", "errors"]
    assert payload["schema_version"] == "1"
    assert payload["query"] == {
        "command": "restaurants",
        "radius_km": 15.0,
        "limit": 100,
        "location_source": "explicit",
    }
    assert payload["partial"] is False
    assert payload["errors"] == []
    assert client.closed is True


def test_restaurant_offers_and_reviews_use_id_workflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FixtureClient()
    monkeypatch.setattr(cli, "get_client", lambda: client)

    for command in (
        ["restaurant", "--id", "1", "--json"],
        ["offers", "--id", "1", "--json"],
        ["reviews", "--id", "1", "--limit", "2", "--json"],
    ):
        result = runner.invoke(cli.app, command)
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["schema_version"] == "1"
        assert payload["partial"] is False
        assert payload["errors"] == []
    assert ("restaurant", "1") in client.calls
    assert ("offers", "1") in client.calls
    assert ("reviews", ("1", 2)) in client.calls


def test_offers_radius_is_offer_ranked_and_id_radius_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FixtureClient()
    monkeypatch.setattr(cli, "get_client", lambda: client)

    result = runner.invoke(
        cli.app,
        ["offers", "--radius", "3", "--latitude", "28", "--longitude", "77", "--json"],
    )
    assert result.exit_code == 0
    assert ("rank", ("offers", 3.0, 100, 4)) in client.calls

    human = runner.invoke(cli.app, ["offers", "--id", "1"])
    assert human.exit_code == 0
    assert "20% off" in human.stdout
    assert "[{" not in human.stdout

    invalid = runner.invoke(cli.app, ["offers", "--id", "1", "--radius", "3"])
    assert invalid.exit_code != 0
    assert "mutually exclusive" in invalid.stdout.lower()


def test_ranking_commands_explain_trend_and_human_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FixtureClient()
    monkeypatch.setattr(cli, "get_client", lambda: client)

    result = runner.invoke(
        cli.app, ["trending", "--radius", "5", "--latitude", "28", "--longitude", "77"]
    )

    assert result.exit_code == 0
    assert "First Cafe" in result.stdout
    assert "rating count: 120" in result.stdout
    assert "insufficient evidence" in result.stdout
    assert "trend:" in result.stdout


def test_invalid_ids_radius_and_limits_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "get_client", FixtureClient)
    for args, text in [
        (["restaurant", "--id", "bad/id"], "id"),
        (["restaurants", "--radius", "0"], "radius"),
        (["reviews", "--id", "1", "--limit", "0"], "limit"),
    ]:
        result = runner.invoke(cli.app, args)
        assert result.exit_code != 0
        assert text in result.stdout.lower()


def test_location_commands_mask_coordinates_unless_revealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = cli.LocationStore(tmp_path / "location.json")
    monkeypatch.setattr(cli, "get_location_store", lambda: store)

    set_result = runner.invoke(
        cli.app, ["location", "set", "--latitude", "28.1", "--longitude", "77.2"]
    )
    assert set_result.exit_code == 0
    shown = runner.invoke(cli.app, ["location", "show", "--json"])
    assert shown.exit_code == 0
    assert "28.1" not in shown.stdout
    assert "77.2" not in shown.stdout
    revealed = runner.invoke(cli.app, ["location", "show", "--reveal", "--json"])
    assert "28.1" in revealed.stdout
    assert "77.2" in revealed.stdout


def test_location_set_rejects_partial_pair_and_clear_removes_saved_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = cli.LocationStore(tmp_path / "location.json")
    monkeypatch.setattr(cli, "get_location_store", lambda: store)
    invalid = runner.invoke(cli.app, ["location", "set", "--latitude", "28.1"])
    assert invalid.exit_code != 0
    assert "both" in invalid.stdout.lower()
    runner.invoke(
        cli.app, ["location", "set", "--latitude", "28.1", "--longitude", "77.2"]
    )
    cleared = runner.invoke(cli.app, ["location", "clear"])
    assert cleared.exit_code == 0
    assert store.load() is None


def test_explicit_coordinates_override_saved_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = FixtureClient()
    store = cli.LocationStore(tmp_path / "location.json")
    store.save(cli.LocationCoordinates(1, 2))
    monkeypatch.setattr(cli, "get_client", lambda: client)
    monkeypatch.setattr(cli, "get_location_store", lambda: store)

    result = runner.invoke(
        cli.app, ["restaurants", "--latitude", "3", "--longitude", "4", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["query"]["location_source"] == "explicit"
