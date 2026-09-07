from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit


def _route_from_request(request: object) -> dict[str, object] | None:
    if not isinstance(request, dict):
        return None
    method = request.get("method")
    url = request.get("url")
    if not isinstance(method, str) or not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if not parsed.hostname or not parsed.path:
        return None
    return {
        "method": method.upper(),
        "host": parsed.hostname.lower(),
        "path": parsed.path,
        "in_scope": method.upper() == "GET",
        "evidence_state": "CAPTURED",
    }


def sanitize_capture(capture: object) -> dict[str, list[dict[str, object]]]:
    """Return only redacted route metadata from a HAR-like capture."""
    if not isinstance(capture, dict):
        raise ValueError("capture must be a JSON object")
    log = capture.get("log")
    entries = (
        log.get("entries", []) if isinstance(log, dict) else capture.get("entries", [])
    )
    if not isinstance(entries, list):
        raise ValueError("capture entries must be a list")
    routes: dict[tuple[str, str, str], dict[str, object]] = {}
    for entry in entries:
        request = entry.get("request") if isinstance(entry, dict) else None
        route = _route_from_request(request)
        if route is None:
            continue
        key = (str(route["method"]), str(route["host"]), str(route["path"]))
        routes[key] = route
    return {
        "routes": sorted(
            routes.values(),
            key=lambda route: (
                str(route["host"]),
                str(route["path"]),
                str(route["method"]),
            ),
        )
    }


def write_sanitized_capture(
    capture: object, input_path: Path, output_path: Path
) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("output must be different from input")
    output_path.write_text(
        json.dumps(sanitize_capture(capture), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    write_sanitized_capture(capture, args.capture, args.output)


if __name__ == "__main__":
    main()
