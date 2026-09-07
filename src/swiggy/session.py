"""Private, allowlisted session material storage without authentication flows."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from swiggy.errors import ConfigurationError

_DEFAULT_SESSION_PATH = Path.home().joinpath(".swiggy-py", "session.json")
_ALLOWED_FIELDS = frozenset({"cookies", "headers"})
_ALLOWED_COOKIE_KEYS = frozenset(
    {
        "sid",
        "sessionid",
        "session_id",
        "csrftoken",
        "csrf-token",
        "access_token",
        "refresh_token",
    }
)
_ALLOWED_HEADER_KEYS = frozenset(
    {"authorization", "x-device-id", "x-csrf-token", "user-agent"}
)


class SessionStore:
    """Atomically read/write a small allowlisted session mapping."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_SESSION_PATH

    def _validate(self, value: Mapping[str, object]) -> dict[str, object]:
        unknown = set(value) - _ALLOWED_FIELDS
        if unknown:
            raise ConfigurationError("session fields must be allowlisted")
        result: dict[str, object] = {}
        for field, allowed in (
            ("cookies", _ALLOWED_COOKIE_KEYS),
            ("headers", _ALLOWED_HEADER_KEYS),
        ):
            section = value.get(field)
            if section is None:
                continue
            if not isinstance(section, Mapping) or set(section) - allowed:
                raise ConfigurationError("session fields must be allowlisted")
            result[field] = dict(section)
        return result

    def save(self, value: Mapping[str, object]) -> None:
        payload = self._validate(value)
        temporary_name: str | None = None
        fd: int | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", dir=self.path.parent
            )
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            else:
                os.chmod(temporary_name, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                fd = None
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
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
            raise ConfigurationError("unable to save session") from exc

    def load(self) -> dict[str, object] | None:
        try:
            value: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError("saved session is unavailable or invalid") from exc
        if not isinstance(value, Mapping):
            raise ConfigurationError("saved session is unavailable or invalid")
        return self._validate(value)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ConfigurationError("unable to clear session") from exc


__all__ = ["SessionStore"]
