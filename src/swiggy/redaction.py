"""Centralized privacy redaction for diagnostics and serialized metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypeVar

T = TypeVar("T")
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "password",
    "cookie",
    "token",
    "otp",
    "session",
    "device",
    "account",
    "phone",
    "email",
)
_BEARER_WITH_LABEL = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+)"
    r"(?!\*{3,}|<redacted>|\[redacted\]|redacted)[^\s,;]+"
)
_BARE_BEARER = re.compile(
    r"(?i)(\bbearer\s+)"
    r"(?!\*{3,}|<redacted>|\[redacted\]|redacted)[^\s,;]+"
)
_QUOTED_KEY_VALUE = re.compile(
    r"""(?i)(["']?(?:password|otp|cookie|access_token|refresh_token)"""
    r"""["']?\s*[:=]\s*)(["'])"""
    r"""(?!\*{3,}|<redacted>|\[redacted\]|redacted)"""
    r"""(?:(?!\2).)*\2"""
)
_UNQUOTED_KEY_VALUE = re.compile(
    r"""(?i)(["']?(?:password|otp|cookie|access_token|refresh_token)"""
    r"""["']?\s*[:=]\s*)"""
    r"""(?!\*{3,}|<redacted>|\[redacted\]|redacted)"""
    r"""[^\s,;"'}&?#]+"""
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)")
_COORDINATES = re.compile(
    r"(?<![\w/])-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}(?![\w/])"
)
_QUOTED_PATH = re.compile(r"""(["'])(/(?:Users|home)/[^"']+)\1""")
_SPACED_PATH = re.compile(
    r"/(?:Users|home)/[^,;)}\]]+?\.(?:har|json|py|txt|yaml|yml|toml|db|sqlite3?)\b"
)
_TOKEN_PATH = re.compile(r"/(?:Users|home)/[^\s,;)}\]]+")


def _sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Replace sensitive values while retaining safe diagnostic context."""

    result = _BEARER_WITH_LABEL.sub(lambda m: f"{m.group(1)}{_REDACTED}", value)
    result = _BARE_BEARER.sub(lambda m: f"{m.group(1)}{_REDACTED}", result)
    result = _QUOTED_KEY_VALUE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}{m.group(2)}", result
    )
    result = _UNQUOTED_KEY_VALUE.sub(lambda m: f"{m.group(1)}{_REDACTED}", result)
    for pattern in (_EMAIL, _PHONE, _COORDINATES):
        result = pattern.sub(_REDACTED, result)
    result = _QUOTED_PATH.sub(lambda m: f"{m.group(1)}{_REDACTED}{m.group(1)}", result)
    result = _SPACED_PATH.sub(_REDACTED, result)
    return _TOKEN_PATH.sub(_REDACTED, result)


def redact(value: T) -> T:
    """Recursively redact strings and sensitive mapping values."""

    if isinstance(value, str):
        return redact_text(value)  # type: ignore[return-value]
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if _sensitive_key(key) else redact(item)
            for key, item in value.items()
        }  # type: ignore[return-value]
    if isinstance(value, list):
        return [redact(item) for item in value]  # type: ignore[return-value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)  # type: ignore[return-value]
    return value


__all__ = ["redact", "redact_text"]
