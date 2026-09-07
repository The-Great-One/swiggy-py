from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.check_public_tree import _SECRET_PATTERN

ROOT = Path(__file__).parents[2]


def test_public_tree_scanner_detects_quoted_secret_keys() -> None:
    assert _SECRET_PATTERN.search('"access_token": "actual-secret"')
    assert _SECRET_PATTERN.search("password='actual-secret'")


def test_public_tree_scanner_passes_current_tracked_tree() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_public_tree.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
