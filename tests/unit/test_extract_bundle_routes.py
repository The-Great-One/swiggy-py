from pathlib import Path

from scripts.extract_bundle_routes import (
    extract_bundle_routes,
    extract_bundle_routes_from_file,
)


def test_extract_bundle_routes_returns_static_candidates_without_network() -> None:
    javascript = (
        'const full = "https://api.example.invalid/v1/dineout";\n'
        'const path = "/v1/offers";\n'
        'const joined = "https" + "://api.example.invalid/v1/reviews";\n'
    )

    assert extract_bundle_routes(javascript) == [
        {
            "method": "GET",
            "host": "api.example.invalid",
            "path": "/v1/dineout",
            "evidence_state": "STATIC ONLY",
        },
        {
            "method": "GET",
            "host": "api.example.invalid",
            "path": "/v1/offers",
            "evidence_state": "STATIC ONLY",
        },
        {
            "method": "GET",
            "host": "api.example.invalid",
            "path": "/v1/reviews",
            "evidence_state": "STATIC ONLY",
        },
    ]


def test_extract_bundle_routes_from_file_is_offline(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.js"
    bundle.write_text('fetch("https://api.example.invalid/v1/menu")', encoding="utf-8")

    assert extract_bundle_routes_from_file(bundle)[0]["path"] == "/v1/menu"


def test_template_literal_url_is_trimmed() -> None:
    routes = extract_bundle_routes("const url = `https://api.example.invalid/v1/menu`;")
    assert routes[0]["host"] == "api.example.invalid"
    assert routes[0]["path"] == "/v1/menu"


def test_bare_path_scanner_rejects_double_slash_segments() -> None:
    routes = extract_bundle_routes('const path = "/v1//offers";')
    assert routes == []
