from __future__ import annotations

import ast
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swiggy.errors import ConfigurationError
from swiggy.location import Coordinates, LocationResolver, LocationStore

LATITUDE = 28.123456
LONGITUDE = 77.654321


def test_location_module_has_no_browser_package_import() -> None:
    tree = ast.parse(Path("src/swiggy/location.py").read_text())
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all("browser" not in ast.unparse(node).lower() for node in imports)


def test_configuration_errors_do_not_include_exact_coordinates(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        LocationResolver(store=LocationStore(tmp_path / "location.json")).resolve(
            LATITUDE, None
        )

    message = str(caught.value)
    assert str(LATITUDE) not in message
    assert str(LONGITUDE) not in message


def test_location_logs_do_not_include_exact_coordinates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = LocationStore(tmp_path / "location.json")
    store.save(
        Coordinates(
            LATITUDE,
            LONGITUDE,
            source="test",
            approval_timestamp=datetime(2026, 9, 7, tzinfo=UTC),
        )
    )

    with caplog.at_level(logging.DEBUG):
        assert store.load() is not None

    assert str(LATITUDE) not in caplog.text
    assert str(LONGITUDE) not in caplog.text


def test_storage_path_defaults_to_home_without_user_specific_absolute_path() -> None:
    assert LocationStore().path == Path.home() / ".swiggy-py" / "location.json"
    source = Path("src/swiggy/location.py").read_text()
    assert "/Users/" not in source
