#!/usr/bin/env python3
"""Fail-closed privacy scan over tracked public-repository files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_SECRET_KEYS = r"(?:authorization|password|otp|cookie|access_token|refresh_token)"
_SECRET_PATTERN = re.compile(
    r"(?i)(?:"
    r"gh" + "o_" + r"|" + "github" + "_pat_" + r"|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN (?:RSA|OPENSSH|PRIVATE) KEY-----|"
    r"Bearer\s+(?!\*{3,}|<redacted>|\[redacted\]|redacted)[A-Za-z0-9._-]{8,}|"
    r"[\"']?" + _SECRET_KEYS + r"[\"']?\s*[:=]\s*"
    r"(?P<quote>[\"'])(?!\*{3,}|<redacted>|\[redacted\]|redacted)"
    r"(?:(?!(?P=quote)).)*(?P=quote)|"
    r"[\"']?" + _SECRET_KEYS + r"[\"']?\s*[:=]\s*"
    r"(?!\*{3,}|<redacted>|\[redacted\]|redacted)"
    r"[^\s,;\"'}&?#]+"
    r")"
)
_LOCAL_PATH_PATTERN = re.compile("/" + r"(?:Users|home)/[^,;)}\]]+")
_PRIVATE_SUFFIXES = (".har", ".apk")
_ALLOWED_CONTEXTS = {
    "tests/contract/test_endpoint_ledger.py": (
        "evidence_source=",
        '("purpose"',
        '("limitations"',
        '("semantic_evidence"',
    ),
    "tests/contract/test_endpoint_source_integrity.py": ('"limitations":',),
    "tests/security/test_location_privacy.py": ("/Users/",),
}
_ALLOWED_SYNTHETIC_FILES = frozenset(
    {
        "scripts/check_public_tree.py",
        "tests/fixtures/synthetic_capture.json",
        "tests/security/test_sanitize_capture.py",
        "tests/security/test_redaction.py",
        "tests/security/test_session_storage.py",
        "tests/security/test_public_tree.py",
        "tests/unit/test_transport.py",
    }
)


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    )
    return [root / item for item in result.stdout.decode().split("\0") if item]


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    for path in tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in _ALLOWED_SYNTHETIC_FILES:
            continue
        if path.suffix.casefold() in _PRIVATE_SUFFIXES or path.name in {
            "session.json",
            "location.json",
        }:
            findings.append(f"{relative}: private artifact")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            allowed_contexts = _ALLOWED_CONTEXTS.get(relative, ())
            if any(marker in line for marker in allowed_contexts):
                continue
            if _SECRET_PATTERN.search(line) or _LOCAL_PATH_PATTERN.search(line):
                findings.append(f"{relative}:{line_number}: sensitive pattern")
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = scan(root)
    if findings:
        print("FAIL")
        print("\n".join(findings))
        return 1
    print("PASS: tracked public tree contains no disallowed sensitive artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
