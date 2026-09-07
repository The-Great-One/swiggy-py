"""Private, deterministic location resolution for read-only requests."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from swiggy.errors import ConfigurationError

_DEFAULT_LOCATION_PATH = Path.home().joinpath(".swiggy-py", "location.json")
_ALLOWED_FIELDS = {"latitude", "longitude", "accuracy", "source", "approval_timestamp"}


def _timestamp() -> datetime:
    return datetime.now(UTC)


def _validate_coordinate(value: float, *, latitude: bool) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ConfigurationError("Location coordinates must be finite numbers")
    minimum, maximum = (-90.0, 90.0) if latitude else (-180.0, 180.0)
    if not minimum <= value <= maximum:
        name = "Latitude" if latitude else "Longitude"
        raise ConfigurationError(f"{name} must be within its valid range")
    return float(value)


@dataclass(frozen=True, slots=True)
class Coordinates:
    """A validated location and its approval metadata."""

    latitude: float
    longitude: float
    accuracy: float | None = None
    source: str = "explicit"
    approval_timestamp: datetime = field(default_factory=_timestamp)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "latitude", _validate_coordinate(self.latitude, latitude=True)
        )
        object.__setattr__(
            self, "longitude", _validate_coordinate(self.longitude, latitude=False)
        )
        if self.accuracy is not None and (
            not isinstance(self.accuracy, (int, float))
            or isinstance(self.accuracy, bool)
            or not math.isfinite(self.accuracy)
            or self.accuracy < 0
        ):
            raise ConfigurationError(
                "Location accuracy must be a non-negative finite number"
            )
        if not isinstance(self.source, str) or not self.source:
            raise ConfigurationError("Location source must be non-empty")
        if self.approval_timestamp.tzinfo is None:
            raise ConfigurationError(
                "Location approval timestamp must include a timezone"
            )


class LocationStore:
    """Read and atomically write an approved location JSON file."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_LOCATION_PATH

    def save(self, location: Coordinates) -> None:
        payload: dict[str, Any] = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "source": location.source,
            "approval_timestamp": location.approval_timestamp.isoformat(),
        }
        if location.accuracy is not None:
            payload["accuracy"] = location.accuracy

        temporary_name: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
            raise ConfigurationError("Unable to save approved location") from exc

    def load(self) -> Coordinates | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                "Saved location is unavailable or invalid"
            ) from exc
        if not isinstance(raw, Mapping) or set(raw) - _ALLOWED_FIELDS:
            raise ConfigurationError("Saved location is unavailable or invalid")
        try:
            required = {"latitude", "longitude", "source", "approval_timestamp"}
            if not required <= set(raw):
                raise ValueError
            timestamp = datetime.fromisoformat(str(raw["approval_timestamp"]))
            return Coordinates(
                latitude=raw["latitude"],
                longitude=raw["longitude"],
                accuracy=raw.get("accuracy"),
                source=raw["source"],
                approval_timestamp=timestamp,
            )
        except (ConfigurationError, TypeError, ValueError, KeyError):
            raise ConfigurationError(
                "Saved location is unavailable or invalid"
            ) from None


class LocationResolver:
    """Resolve explicit, approved, then browser-detected coordinates."""

    def __init__(
        self,
        store: LocationStore | None = None,
        browser_detector: Callable[[], Coordinates | None] | None = None,
    ) -> None:
        self.store = store or LocationStore()
        self.browser_detector = browser_detector

    def resolve(
        self, explicit_latitude: float | None, explicit_longitude: float | None
    ) -> Coordinates:
        if (explicit_latitude is None) != (explicit_longitude is None):
            raise ConfigurationError("Provide both latitude and longitude together")
        if explicit_latitude is not None and explicit_longitude is not None:
            return Coordinates(explicit_latitude, explicit_longitude, source="explicit")

        saved = self.store.load()
        if saved is not None:
            return saved
        if self.browser_detector is not None:
            detected = self.browser_detector()
            if detected is not None:
                return detected
        raise ConfigurationError(
            "No location available; provide both latitude and longitude, "
            "approve a saved location, "
            "or configure a browser detector"
        )


__all__ = ["Coordinates", "LocationResolver", "LocationStore"]
