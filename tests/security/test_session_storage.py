from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from swiggy.errors import ConfigurationError
from swiggy.session import SessionStore


def test_session_store_round_trips_allowlisted_fields_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "session.json"
    store = SessionStore(path)
    value = {"cookies": {"sid": "secret"}, "headers": {"x-device-id": "device"}}

    store.save(value)

    assert store.load() == value
    assert json.loads(path.read_text()) == value
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(".session.json.*"))


def test_session_store_rejects_unknown_fields_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    store = SessionStore(path)

    with pytest.raises(ConfigurationError, match="allowlisted"):
        store.save({"password": "secret"})

    assert not path.exists()


def test_session_store_clear_is_idempotent(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "session.json")
    store.clear()
    assert store.load() is None
