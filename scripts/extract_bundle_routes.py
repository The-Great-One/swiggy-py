from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

_URL_RE = re.compile(r"https?://[^\"'\s)`]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.])/[A-Za-z0-9_.{}-]+(?:/[A-Za-z0-9_.{}-]+)+")
_COMPOSED_URL_RE = re.compile(
    r"[\"'](https?)[\"']\s*\+\s*[\"'](:\/\/[^\"']+)[\"']",
    re.IGNORECASE,
)


def _route(method: str, host: str, path: str) -> dict[str, object]:
    return {
        "method": method.upper(),
        "host": host.lower(),
        "path": path,
        "evidence_state": "STATIC ONLY",
    }


def extract_bundle_routes(javascript: str) -> list[dict[str, object]]:
    """Extract candidate route shapes from already-downloaded JavaScript.

    This is intentionally a static census. It does not import, execute, or fetch
    any code and labels every result STATIC ONLY.
    """
    candidates: dict[tuple[str, str, str], dict[str, object]] = {}
    known_hosts: set[str] = set()
    url_spans: list[tuple[int, int]] = []
    for match in _URL_RE.finditer(javascript):
        url_spans.append(match.span())
        parsed = urlsplit(match.group(0).rstrip(".,;"))
        if parsed.hostname and parsed.path:
            host = parsed.hostname.lower()
            known_hosts.add(host)
            value = _route("GET", host, parsed.path)
            candidates[("GET", host, parsed.path)] = value
    for match in _COMPOSED_URL_RE.finditer(javascript):
        url_spans.append(match.span())
        parsed = urlsplit(match.group(1) + match.group(2))
        if parsed.hostname and parsed.path:
            host = parsed.hostname.lower()
            known_hosts.add(host)
            value = _route("GET", host, parsed.path)
            candidates[("GET", host, parsed.path)] = value
    for match in _PATH_RE.finditer(javascript):
        path = match.group(0)
        if path.split("/", 2)[1].find(".") >= 0:
            continue
        if any(start <= match.start() < end for start, end in url_spans):
            continue
        host = next(iter(known_hosts)) if len(known_hosts) == 1 else "unknown.invalid"
        value = _route("GET", host, path)
        candidates.setdefault(("GET", host, path), value)
    return sorted(
        candidates.values(),
        key=lambda route: (
            str(route["host"]),
            str(route["path"]),
            str(route["method"]),
        ),
    )


def extract_bundle_routes_from_file(path: Path) -> list[dict[str, object]]:
    return extract_bundle_routes(path.read_text(encoding="utf-8"))


def write_extracted_routes(bundle_path: Path, output_path: Path) -> None:
    if bundle_path.resolve() == output_path.resolve():
        raise ValueError("output must be different from input bundle")
    payload = {"routes": extract_bundle_routes_from_file(bundle_path)}
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        write_extracted_routes(args.bundle, args.output)
    else:
        result = {"routes": extract_bundle_routes_from_file(args.bundle)}
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
