from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path
from typing import cast

REQUIRED_FIELDS = frozenset(
    {
        "id",
        "method",
        "host",
        "path",
        "state",
        "auth",
        "location",
        "pagination",
        "purpose",
        "allowed_inputs",
        "observed_fields",
        "limitations",
        "evidence_source",
        "semantic_evidence",
        "last_verified",
        "in_scope",
        "safe_to_replay",
    }
)
EVIDENCE_STATES = frozenset(
    {"LIVE VERIFIED", "CAPTURED", "STATIC ONLY", "AUTH REQUIRED", "RETIRED/BROKEN"}
)
AUTH_STATES = frozenset({"guest", "optional", "required"})
LOCATION_STATES = frozenset({"none", "query", "headers", "body"})
PAGINATION_STATES = frozenset({"none", "offset", "cursor", "unknown"})
FORBIDDEN_MUTATION_TERMS = frozenset(
    {"booking", "reservation", "payment", "cart", "cancel", "cancellation", "account"}
)
_SENSITIVE_VALUE = re.compile(
    r"(?ix)(?:"
    r"authorization\s*[:=]\s*bearer\s+(?!\*{3,}(?:\s|$))[A-Za-z0-9._-]{8,}|"
    r"cookie\s*[:=]\s*(?!\*{3,}(?:\s|$)|<redacted>|\\[redacted\\]|redacted)\S+|"
    r"(?:access|refresh)?_?token\s*[:=]\s*(?!\*{3,}(?:\s|$)|<redacted>|\\[redacted\\]|redacted)\S+|"
    r"otp\s*[:=]\s*(?!\*{3,}(?:\s|$)|<redacted>|\\[redacted\\]|redacted)\S+|"
    r"password\s*[:=]\s*(?!\*{3,}(?:\s|$)|<redacted>|\\[redacted\\]|redacted)\S+|"
    r"session(?:id)?\s*[:=]\s*(?!\*{3,}(?:\s|$)|<redacted>|\\[redacted\\]|redacted)\S+"
    r")"
)
_SEMANTIC_SUCCESS_ASSERTION = re.compile(
    r"(?i)\b(?:response|payload)\s+"
    r"(?:contained|included|returned|provided|represented|matched|confirmed)\b"
)
_SEMANTIC_FAILURE_TEXT = re.compile(
    r"(?i)\b(?:error|login|sign[ -]?in|fallback|unauthorized|forbidden)\b"
)
_HOST_LITERAL = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,63}$", re.IGNORECASE)
_URL_LITERAL = re.compile(r"^https?://")
_API_PATH_LITERAL = re.compile(r"^/[A-Za-z0-9_.{}-]+(?:/[A-Za-z0-9_./{}-]+)?$")
_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

RouteKey = tuple[str, str, str]


class LedgerValidationError(ValueError):
    """Raised when endpoint evidence fails closed validation."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    id: str
    method: str
    host: str
    path: str
    state: str
    auth: str
    location: str
    pagination: str
    purpose: str
    allowed_inputs: tuple[str, ...]
    observed_fields: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_source: str
    semantic_evidence: str
    last_verified: str | None
    in_scope: bool
    safe_to_replay: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Endpoint:
        missing = REQUIRED_FIELDS - value.keys()
        if missing:
            names = ", ".join(sorted(missing))
            raise LedgerValidationError(f"missing required fields: {names}")
        return cls(
            id=_string(value, "id"),
            method=_string(value, "method"),
            host=_string(value, "host"),
            path=_string(value, "path"),
            state=_string(value, "state"),
            auth=_string(value, "auth"),
            location=_string(value, "location"),
            pagination=_string(value, "pagination"),
            purpose=_string(value, "purpose"),
            allowed_inputs=_string_tuple(value, "allowed_inputs"),
            observed_fields=_string_tuple(value, "observed_fields"),
            limitations=_string_tuple(value, "limitations"),
            evidence_source=_string(value, "evidence_source"),
            semantic_evidence=_string(value, "semantic_evidence", allow_empty=True),
            last_verified=_optional_string(value, "last_verified"),
            in_scope=_boolean(value, "in_scope"),
            safe_to_replay=_boolean(value, "safe_to_replay"),
        )

    @property
    def route_key(self) -> RouteKey:
        return (self.method, self.host, self.path)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "method": self.method,
            "host": self.host,
            "path": self.path,
            "state": self.state,
            "auth": self.auth,
            "location": self.location,
            "pagination": self.pagination,
            "purpose": self.purpose,
            "allowed_inputs": list(self.allowed_inputs),
            "observed_fields": list(self.observed_fields),
            "limitations": list(self.limitations),
            "evidence_source": self.evidence_source,
            "semantic_evidence": self.semantic_evidence,
            "last_verified": self.last_verified,
            "in_scope": self.in_scope,
            "safe_to_replay": self.safe_to_replay,
        }


class EndpointRegistry:
    """Runtime-only registry containing safe, semantically verified GET routes."""

    def __init__(self, endpoints: Iterable[Endpoint]) -> None:
        values = tuple(endpoints)
        by_id: dict[str, Endpoint] = {}
        routes: set[RouteKey] = set()
        for endpoint in values:
            if endpoint.state != "LIVE VERIFIED":
                raise ValueError(f"endpoint {endpoint.id!r} is not LIVE VERIFIED")
            if endpoint.method != "GET":
                raise ValueError(f"endpoint {endpoint.id!r} must use GET")
            if not endpoint.safe_to_replay:
                raise ValueError(f"endpoint {endpoint.id!r} is not safe_to_replay")
            if endpoint.id in by_id:
                raise ValueError(f"duplicate endpoint id: {endpoint.id}")
            if endpoint.route_key in routes:
                raise ValueError(f"duplicate endpoint route: {endpoint.route_key!r}")
            by_id[endpoint.id] = endpoint
            routes.add(endpoint.route_key)
        self._endpoints = values
        self._by_id = by_id

    @classmethod
    def from_package_data(cls) -> EndpointRegistry:
        resource = resources.files("swiggy").joinpath("_endpoint_registry.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise LedgerValidationError(
                "generated endpoint registry has invalid schema"
            )
        raw_records = payload.get("endpoints")
        if not isinstance(raw_records, list):
            raise LedgerValidationError(
                "generated endpoint registry endpoints must be a list"
            )
        records = _mapping_list(raw_records)
        endpoints = validate_records(records)
        runtime = (
            endpoint
            for endpoint in endpoints
            if endpoint.in_scope
            and endpoint.state == "LIVE VERIFIED"
            and endpoint.method == "GET"
            and endpoint.safe_to_replay
        )
        return cls(runtime)

    def __iter__(self) -> Iterator[Endpoint]:
        return iter(self._endpoints)

    def get(self, endpoint_id: str) -> Endpoint:
        try:
            return self._by_id[endpoint_id]
        except KeyError as error:
            raise KeyError(f"unknown endpoint id: {endpoint_id}") from error


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    missing: tuple[RouteKey, ...]
    excluded: tuple[RouteKey, ...]
    undocumented: tuple[RouteKey, ...]


@dataclass(frozen=True, slots=True)
class SourceViolation:
    path: Path
    line: int
    kind: str
    literal: str


def parse_endpoint_blocks(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{3,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2)))

    records: list[dict[str, object]] = []
    endpoint_fence_lines: list[int] = []
    for index, line in enumerate(lines):
        if line.strip() == "```endpoint-json":
            endpoint_fence_lines.append(index)

    for fence_index, start in enumerate(endpoint_fence_lines, start=1):
        containing = [heading for heading in headings if heading[0] < start]
        if not containing:
            raise LedgerValidationError(
                f"endpoint-json block {fence_index} is orphaned; "
                "add an endpoint subsection"
            )
        section = containing[-1]
        next_heading = next(
            (
                heading
                for heading in headings
                if heading[0] > section[0] and heading[1] <= section[1]
            ),
            (len(lines), 0, ""),
        )
        section_fences = [
            line_no
            for line_no in endpoint_fence_lines
            if section[0] < line_no < next_heading[0]
        ]
        if len(section_fences) != 1:
            raise LedgerValidationError(
                f"endpoint subsection {section[2]!r} must contain "
                "exactly one endpoint-json block"
            )
        close = next(
            (i for i in range(start + 1, len(lines)) if lines[i].strip() == "```"), None
        )
        if close is None or close >= next_heading[0]:
            raise LedgerValidationError(
                f"endpoint-json block {fence_index} is not closed"
            )
        block = "\n".join(lines[start + 1 : close])
        try:
            value = json.loads(block)
        except json.JSONDecodeError as error:
            raise LedgerValidationError(
                f"endpoint-json block {fence_index} is invalid JSON: {error.msg}"
            ) from error
        if not isinstance(value, dict):
            raise LedgerValidationError(
                f"endpoint-json block {fence_index} must be an object"
            )
        records.append(cast(dict[str, object], value))
    return records


def validate_records(records: Sequence[Mapping[str, object]]) -> tuple[Endpoint, ...]:
    endpoints: list[Endpoint] = []
    ids: set[str] = set()
    routes: set[RouteKey] = set()
    for record in records:
        endpoint = Endpoint.from_mapping(record)
        extra = record.keys() - REQUIRED_FIELDS
        if extra:
            names = ", ".join(sorted(extra))
            raise LedgerValidationError(f"unexpected endpoint fields: {names}")
        _validate_endpoint(endpoint)
        if endpoint.id in ids:
            raise LedgerValidationError(f"duplicate endpoint id: {endpoint.id}")
        if endpoint.route_key in routes:
            raise LedgerValidationError(
                f"duplicate endpoint route: {endpoint.route_key!r}"
            )
        ids.add(endpoint.id)
        routes.add(endpoint.route_key)
        endpoints.append(endpoint)
    return tuple(endpoints)


def reconcile_inventory(
    records: Sequence[Mapping[str, object]], inventory: Mapping[str, object]
) -> ReconciliationReport:
    raw_routes = inventory.get("routes")
    if not isinstance(raw_routes, list):
        raise LedgerValidationError("route inventory must contain a routes list")
    inventory_routes = _mapping_list(raw_routes)
    in_scope: set[RouteKey] = set()
    excluded: set[RouteKey] = set()
    for route in inventory_routes:
        key = _route_key(route)
        scope = route.get("in_scope")
        if not isinstance(scope, bool):
            raise LedgerValidationError(
                f"inventory route {key!r} needs boolean in_scope"
            )
        if scope:
            in_scope.add(key)
        else:
            reason = route.get("exclusion_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise LedgerValidationError(
                    f"excluded inventory route {key!r} needs exclusion_reason"
                )
            excluded.add(key)
    ledger_routes = {
        endpoint.route_key
        for endpoint in validate_records(records)
        if endpoint.in_scope
    }
    return ReconciliationReport(
        missing=tuple(sorted(in_scope - ledger_routes)),
        excluded=tuple(sorted(excluded)),
        undocumented=tuple(sorted(ledger_routes - in_scope)),
    )


def generated_registry_payload(
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    endpoints = validate_records(records)
    return {
        "schema_version": 1,
        "generated_from": "API_ENDPOINTS.md",
        "endpoints": [
            endpoint.as_dict() for endpoint in sorted(endpoints, key=lambda x: x.id)
        ],
    }


def find_handwritten_endpoint_literals(root: Path) -> tuple[SourceViolation, ...]:
    violations: list[SourceViolation] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.expr):
                continue
            literal = _static_string(node)
            if literal is None:
                continue
            kind = _endpoint_literal_kind(literal)
            if kind is not None:
                violations.append(
                    SourceViolation(
                        path=path,
                        line=node.lineno,
                        kind=kind,
                        literal=literal,
                    )
                )
    return tuple(violations)


def _validate_endpoint(endpoint: Endpoint) -> None:
    if not _ID_PATTERN.fullmatch(endpoint.id):
        raise LedgerValidationError(f"invalid endpoint id: {endpoint.id!r}")
    if endpoint.method != "GET":
        raise LedgerValidationError(
            f"endpoint {endpoint.id!r} must use the read-only GET method"
        )
    if endpoint.state not in EVIDENCE_STATES:
        raise LedgerValidationError(f"invalid state for endpoint {endpoint.id!r}")
    if endpoint.auth not in AUTH_STATES:
        raise LedgerValidationError(f"invalid auth for endpoint {endpoint.id!r}")
    if endpoint.location not in LOCATION_STATES:
        raise LedgerValidationError(f"invalid location for endpoint {endpoint.id!r}")
    if endpoint.pagination not in PAGINATION_STATES:
        raise LedgerValidationError(f"invalid pagination for endpoint {endpoint.id!r}")
    if not _HOST_LITERAL.fullmatch(endpoint.host) or "/" in endpoint.host:
        raise LedgerValidationError(f"invalid host for endpoint {endpoint.id!r}")
    if (
        not endpoint.path.startswith("/")
        or "?" in endpoint.path
        or "#" in endpoint.path
    ):
        raise LedgerValidationError(f"invalid path for endpoint {endpoint.id!r}")
    haystack = " ".join((endpoint.id, endpoint.path, endpoint.purpose)).lower()
    for term in sorted(FORBIDDEN_MUTATION_TERMS):
        if re.search(rf"(?<![a-z]){re.escape(term)}(?:s|ed|ing)?(?![a-z])", haystack):
            raise LedgerValidationError(
                f"endpoint {endpoint.id!r} contains forbidden mutation term {term!r}"
            )
    if not endpoint.evidence_source.strip():
        raise LedgerValidationError(f"endpoint {endpoint.id!r} needs evidence_source")
    metadata_values = (
        endpoint.purpose,
        endpoint.evidence_source,
        endpoint.semantic_evidence,
        *endpoint.allowed_inputs,
        *endpoint.observed_fields,
        *endpoint.limitations,
    )
    if any(_SENSITIVE_VALUE.search(value) for value in metadata_values):
        raise LedgerValidationError(
            f"endpoint {endpoint.id!r} metadata contains an unredacted sensitive value"
        )
    if endpoint.state == "LIVE VERIFIED":
        if endpoint.last_verified is None:
            raise LedgerValidationError(
                f"endpoint {endpoint.id!r} needs last_verified when LIVE VERIFIED"
            )
        try:
            date.fromisoformat(endpoint.last_verified)
        except ValueError as error:
            raise LedgerValidationError(
                f"endpoint {endpoint.id!r} has invalid last_verified date"
            ) from error
        if not endpoint.semantic_evidence.strip():
            raise LedgerValidationError(
                f"endpoint {endpoint.id!r} needs semantic_evidence when LIVE VERIFIED"
            )
        _validate_semantic_evidence(endpoint)
        if not endpoint.evidence_source.startswith("replay:"):
            raise LedgerValidationError(
                f"endpoint {endpoint.id!r} LIVE VERIFIED evidence_source "
                "must be replay evidence"
            )
    elif endpoint.last_verified is not None:
        raise LedgerValidationError(
            f"endpoint {endpoint.id!r} cannot have last_verified before LIVE VERIFIED"
        )


def _validate_semantic_evidence(endpoint: Endpoint) -> None:
    evidence = endpoint.semantic_evidence
    missing_fields = [
        field
        for field in endpoint.observed_fields
        if field.casefold() not in evidence.casefold()
    ]
    if (
        missing_fields
        or _SEMANTIC_SUCCESS_ASSERTION.search(evidence) is None
        or _SEMANTIC_FAILURE_TEXT.search(evidence) is not None
    ):
        raise LedgerValidationError(
            f"endpoint {endpoint.id!r} semantic_evidence must assert "
            "the observed_fields and expected successful response meaning, "
            "not status/error/login fallback text"
        )


def _string(value: Mapping[str, object], key: str, *, allow_empty: bool = False) -> str:
    item = value[key]
    if not isinstance(item, str) or (not allow_empty and not item.strip()):
        raise LedgerValidationError(f"{key} must be a non-empty string")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    item = value[key]
    if item is not None and not isinstance(item, str):
        raise LedgerValidationError(f"{key} must be a string or null")
    return item


def _boolean(value: Mapping[str, object], key: str) -> bool:
    item = value[key]
    if not isinstance(item, bool):
        raise LedgerValidationError(f"{key} must be boolean")
    return item


def _string_tuple(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    item = value[key]
    if not isinstance(item, list) or any(
        not isinstance(element, str) or not element.strip() for element in item
    ):
        raise LedgerValidationError(f"{key} must be a list of non-empty strings")
    return tuple(cast(list[str], item))


def _mapping_list(values: list[object]) -> list[Mapping[str, object]]:
    if any(not isinstance(value, dict) for value in values):
        raise LedgerValidationError("records must be JSON objects")
    return cast(list[Mapping[str, object]], values)


def _route_key(route: Mapping[str, object]) -> RouteKey:
    return (
        _string(route, "method"),
        _string(route, "host"),
        _string(route, "path"),
    )


def _static_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for joined_value in node.values:
            if isinstance(joined_value, ast.Constant) and isinstance(
                joined_value.value, str
            ):
                parts.append(joined_value.value)
            elif (
                isinstance(joined_value, ast.FormattedValue)
                and joined_value.conversion == -1
            ):
                part = _static_string(joined_value.value)
                if part is None:
                    return None
                parts.append(part)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        template = _static_string(node.left)
        if template is None:
            return None
        if isinstance(node.right, ast.Constant) and isinstance(node.right.value, str):
            format_values: object = node.right.value
        else:
            format_values = _static_string_sequence(node.right)
            if format_values is None:
                return None
        try:
            return template % format_values
        except (TypeError, ValueError):
            return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        receiver = _static_string(node.func.value)
        if node.func.attr == "format" and receiver is not None:
            positional: list[str] = []
            for argument in node.args:
                value = _static_string(argument)
                if value is None:
                    return None
                positional.append(value)
            keywords: dict[str, str] = {}
            for keyword in node.keywords:
                if keyword.arg is None:
                    return None
                value = _static_string(keyword.value)
                if value is None:
                    return None
                keywords[keyword.arg] = value
            try:
                return receiver.format(*positional, **keywords)
            except (IndexError, KeyError, ValueError):
                return None
        if (
            node.func.attr == "join"
            and receiver is not None
            and len(node.args) == 1
            and not node.keywords
        ):
            values = _static_string_sequence(node.args[0])
            if values is not None:
                return receiver.join(values)
    return None


def _static_string_sequence(node: ast.expr) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    values: list[str] = []
    for element in node.elts:
        value = _static_string(element)
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _endpoint_literal_kind(literal: str) -> str | None:
    if _URL_LITERAL.match(literal):
        return "url"
    if _HOST_LITERAL.fullmatch(literal):
        return "host"
    if _API_PATH_LITERAL.fullmatch(literal):
        return "path"
    return None
