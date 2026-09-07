from __future__ import annotations

import json
from pathlib import Path

from swiggy.endpoints import (
    find_handwritten_endpoint_literals,
    generated_registry_payload,
    parse_endpoint_blocks,
)

ROOT = Path(__file__).parents[2]


def test_generated_registry_exactly_matches_markdown_authority() -> None:
    records = parse_endpoint_blocks(ROOT / "API_ENDPOINTS.md")
    expected = generated_registry_payload(records)
    actual = json.loads(
        (ROOT / "src/swiggy/_endpoint_registry.json").read_text(encoding="utf-8")
    )

    assert actual == expected


def test_every_production_python_module_avoids_handwritten_endpoint_literals() -> None:
    violations = find_handwritten_endpoint_literals(ROOT / "src/swiggy")

    assert violations == ()


def test_source_scan_ignores_dotted_local_data_filenames(tmp_path: Path) -> None:
    module = tmp_path / "paths.py"
    module.write_text(
        'LOCATION = Path.home().joinpath(".swiggy-py", "location.json")\n',
        encoding="utf-8",
    )

    assert find_handwritten_endpoint_literals(tmp_path) == ()


def test_source_scan_folds_supported_constant_string_expressions(
    tmp_path: Path,
) -> None:
    module = tmp_path / "folded.py"
    module.write_text(
        'FSTRING = f\'{"https"}://{"api"}{".example.invalid"}/v1/dineout\'\n'
        'PERCENT = "%s://%s%s" % ("https", "api", ".example.invalid/v1/offers")\n'
        'FORMAT = "{scheme}://{left}{right}/v1/reviews".format(\n'
        '    scheme="https", left="api", right=".example.invalid"\n'
        ")\n"
        'JOINED = "".join(("https", "://", "api", ".example.invalid", "/v1/menu"))\n',
        encoding="utf-8",
    )

    literals = {
        violation.literal for violation in find_handwritten_endpoint_literals(tmp_path)
    }

    assert literals >= {
        "https://api.example.invalid/v1/dineout",
        "https://api.example.invalid/v1/offers",
        "https://api.example.invalid/v1/reviews",
        "https://api.example.invalid/v1/menu",
    }


def test_source_scan_keeps_plus_and_short_path_detection(tmp_path: Path) -> None:
    module = tmp_path / "existing.py"
    module.write_text(
        'COMPOSED = "https" + "://api.example.invalid/v1/dineout"\n'
        'SHORT_PATH = "/dineout"\n',
        encoding="utf-8",
    )

    literals = {
        violation.literal for violation in find_handwritten_endpoint_literals(tmp_path)
    }

    assert "https://api.example.invalid/v1/dineout" in literals
    assert "/dineout" in literals


def test_source_scan_folds_fstrings_format_percent_and_join(tmp_path: Path) -> None:
    module = tmp_path / "folded.py"
    module.write_text(
        'F = f\'{"https"}://{"api"}{".example.invalid"}/v1/f\'\n'
        'P = "%s://%s%s" % ("https", "api", ".example.invalid/v1/p")\n'
        'M = "{scheme}://{host}/v1/m".format(\n'
        '    scheme="https", host="api.example.invalid"\n'
        ")\n"
        'J = "".join(("https", "://", "api.example.invalid", "/v1/j"))\n',
        encoding="utf-8",
    )
    literals = {v.literal for v in find_handwritten_endpoint_literals(tmp_path)}
    assert literals >= {
        "https://api.example.invalid/v1/f",
        "https://api.example.invalid/v1/p",
        "https://api.example.invalid/v1/m",
        "https://api.example.invalid/v1/j",
    }


def test_source_scan_folds_single_percent_and_positional_format(tmp_path: Path) -> None:
    module = tmp_path / "positional.py"
    module.write_text(
        'P = "/%s/dineout" % "v1"\n'
        'F = "{}/v1/dineout".format("https://api.example.invalid")\n',
        encoding="utf-8",
    )
    literals = {v.literal for v in find_handwritten_endpoint_literals(tmp_path)}
    assert "/v1/dineout" in literals
    assert "https://api.example.invalid/v1/dineout" in literals


def test_source_scan_does_not_bypass_json_urls_or_paths(tmp_path: Path) -> None:
    module = tmp_path / "json_routes.py"
    module.write_text(
        'URL = "https://api.example.invalid/v1/data.json"\nPATH = "/v1/data.json"\n',
        encoding="utf-8",
    )

    violations = find_handwritten_endpoint_literals(tmp_path)

    assert {violation.literal for violation in violations} >= {
        "https://api.example.invalid/v1/data.json",
        "/v1/data.json",
    }


def test_redacted_metadata_placeholders_are_allowed() -> None:
    record = {
        "id": "synthetic",
        "method": "GET",
        "host": "api.example.invalid",
        "path": "/v1/dineout",
        "state": "STATIC ONLY",
        "auth": "guest",
        "location": "none",
        "pagination": "none",
        "purpose": "Synthetic endpoint",
        "allowed_inputs": [],
        "observed_fields": ["venues"],
        "limitations": ["Authorization: Bearer <redacted>", "session=[redacted]"],
        "evidence_source": "capture: cookie: *** for synthetic test",
        "semantic_evidence": "",
        "last_verified": None,
        "in_scope": True,
        "safe_to_replay": False,
    }
    from swiggy.endpoints import validate_records

    validate_records([record])
