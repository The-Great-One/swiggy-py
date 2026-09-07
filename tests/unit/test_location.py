from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swiggy.errors import ConfigurationError
from swiggy.location import Coordinates, LocationResolver, LocationStore

APPROVED_AT = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def coordinates(lat: float = 28.5, lon: float = 77.1) -> Coordinates:
    return Coordinates(
        latitude=lat,
        longitude=lon,
        accuracy=25.0,
        source="approved-test",
        approval_timestamp=APPROVED_AT,
    )


def test_complete_explicit_pair_wins_without_storage_or_browser(tmp_path: Path) -> None:
    calls: list[str] = []
    store = LocationStore(tmp_path / "location.json")
    store.save(coordinates(1.0, 2.0))

    result = LocationResolver(
        store=store, browser_detector=lambda: calls.append("browser")
    ).resolve(3.0, 4.0)

    assert result.latitude == 3.0
    assert result.longitude == 4.0
    assert result.source == "explicit"
    assert calls == []


def test_partial_explicit_pair_raises_without_falling_through(tmp_path: Path) -> None:
    calls: list[str] = []
    store = LocationStore(tmp_path / "location.json")
    store.save(coordinates())

    with pytest.raises(ConfigurationError, match="both latitude and longitude"):
        LocationResolver(
            store=store, browser_detector=lambda: calls.append("browser")
        ).resolve(3.0, None)

    assert calls == []


def test_approved_saved_location_is_second_source(tmp_path: Path) -> None:
    saved = coordinates()
    store = LocationStore(tmp_path / "location.json")
    store.save(saved)

    result = LocationResolver(
        store=store, browser_detector=lambda: pytest.fail("not called")
    ).resolve(None, None)

    assert result == saved


def test_injected_browser_detector_is_third_source(tmp_path: Path) -> None:
    detected = coordinates(19.0, 72.0)
    result = LocationResolver(
        store=LocationStore(tmp_path / "missing.json"),
        browser_detector=lambda: detected,
    ).resolve(None, None)

    assert result == detected


def test_absence_has_actionable_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="latitude.*longitude|saved.*browser"):
        LocationResolver(store=LocationStore(tmp_path / "missing.json")).resolve(
            None, None
        )


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90.0001, 0.0), (90.0001, 0.0), (0.0, -180.0001), (0.0, 180.0001)],
)
def test_coordinates_validate_ranges(latitude: float, longitude: float) -> None:
    with pytest.raises(ConfigurationError):
        Coordinates(latitude, longitude)


def test_store_persists_only_approved_fields_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "location.json"
    saved = coordinates()
    store = LocationStore(path)

    store.save(saved)

    assert json.loads(path.read_text()) == {
        "latitude": 28.5,
        "longitude": 77.1,
        "accuracy": 25.0,
        "source": "approved-test",
        "approval_timestamp": APPROVED_AT.isoformat(),
    }
    assert store.load() == saved


def test_store_replaces_file_atomically_and_uses_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "location.json"
    store = LocationStore(path)
    store.save(coordinates(1.0, 2.0))
    store.save(coordinates(3.0, 4.0))

    assert store.load() == coordinates(3.0, 4.0)
    assert not list(tmp_path.glob(".location.json.*"))
    if hasattr(path.stat(), "st_mode"):
        assert path.stat().st_mode & 0o777 == 0o600
