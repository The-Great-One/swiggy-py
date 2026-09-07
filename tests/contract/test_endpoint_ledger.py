from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from swiggy.endpoints import (
    Endpoint,
    EndpointRegistry,
    LedgerValidationError,
    parse_endpoint_blocks,
    reconcile_inventory,
    validate_records,
)

ROOT = Path(__file__).parents[2]


def endpoint_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "synthetic-discovery",
        "method": "GET",
        "host": "api.example.invalid",
        "path": "/v1/dineout/discovery",
        "state": "STATIC ONLY",
        "auth": "guest",
        "location": "query",
        "pagination": "cursor",
        "purpose": "Discover synthetic Dineout venues",
        "allowed_inputs": ["lat", "lng", "cursor"],
        "observed_fields": ["venues", "next_cursor"],
        "limitations": ["Synthetic contract only"],
        "evidence_source": "static: synthetic test fixture",
        "semantic_evidence": "",
        "last_verified": None,
        "in_scope": True,
        "safe_to_replay": False,
    }
    record.update(overrides)
    return record


def live_endpoint(**overrides: object) -> Endpoint:
    values = endpoint_record(
        state="LIVE VERIFIED",
        evidence_source="replay: redacted synthetic response",
        semantic_evidence="Returned the requested synthetic venue collection",
        last_verified=date(2026, 9, 7).isoformat(),
        safe_to_replay=True,
    )
    values.update(overrides)
    return Endpoint.from_mapping(values)


def test_markdown_endpoint_json_is_the_only_parsed_authority(tmp_path: Path) -> None:
    ignored = endpoint_record(id="ignored")
    accepted = endpoint_record(id="accepted")
    ledger = tmp_path / "API_ENDPOINTS.md"
    ledger.write_text(
        "# Ledger\n\n## Endpoint records\n\n### ignored\n\n```json\n"
        + json.dumps(ignored)
        + "\n```\n\n### accepted\n\n```endpoint-json\n"
        + json.dumps(accepted)
        + "\n```\n",
        encoding="utf-8",
    )

    assert [record["id"] for record in parse_endpoint_blocks(ledger)] == ["accepted"]


def test_repository_ledger_and_route_inventory_reconcile() -> None:
    records = parse_endpoint_blocks(ROOT / "API_ENDPOINTS.md")
    inventory = json.loads(
        (ROOT / "tests/fixtures/route_inventory.json").read_text(encoding="utf-8")
    )

    report = reconcile_inventory(records, inventory)

    assert report.missing == ()
    assert report.excluded == ()
    assert report.undocumented == ()


def test_duplicate_ids_and_routes_are_rejected() -> None:
    duplicate_id = endpoint_record()
    duplicate_route = endpoint_record(id="other-id")

    with pytest.raises(LedgerValidationError, match="duplicate endpoint id"):
        validate_records([duplicate_id, deepcopy(duplicate_id)])
    with pytest.raises(LedgerValidationError, match="duplicate endpoint route"):
        validate_records([duplicate_id, duplicate_route])


def test_every_required_field_is_mandatory() -> None:
    record = endpoint_record()
    record.pop("allowed_inputs")

    with pytest.raises(
        LedgerValidationError, match="missing required fields.*allowed_inputs"
    ):
        validate_records([record])


def test_evidence_collections_and_redacted_source_are_validated() -> None:
    for field in ("allowed_inputs", "observed_fields", "limitations"):
        record = endpoint_record(**{field: "not-a-list"})
        with pytest.raises(LedgerValidationError, match=field):
            validate_records([record])

    with pytest.raises(LedgerValidationError, match="evidence_source"):
        validate_records([endpoint_record(evidence_source="")])
    with pytest.raises(LedgerValidationError, match="redacted"):
        validate_records(
            [
                endpoint_record(
                    evidence_source="capture: Authorization: Bearer unredactedvalue"
                )
            ]
        )


def test_live_verified_records_require_observed_fields_and_expected_meaning() -> None:
    invalid_evidence = (
        "HTTP 200",
        "Request succeeded with status 200",
        "Response contained an error payload with venues and next_cursor",
        "Login fallback returned venues and next_cursor",
    )
    for semantic_evidence in invalid_evidence:
        with pytest.raises(LedgerValidationError, match="semantic_evidence"):
            validate_records(
                [
                    endpoint_record(
                        state="LIVE VERIFIED",
                        last_verified="2026-09-07",
                        evidence_source="replay: redacted fixture",
                        semantic_evidence=semantic_evidence,
                    )
                ]
            )

    validate_records(
        [
            endpoint_record(
                state="LIVE VERIFIED",
                last_verified="2026-09-07",
                evidence_source="replay: redacted fixture",
                semantic_evidence=(
                    "Response contained venues for the requested location and "
                    "next_cursor for further discovery results"
                ),
            )
        ]
    )


def test_live_verified_records_require_valid_semantic_evidence_and_date() -> None:
    with pytest.raises(LedgerValidationError, match="last_verified"):
        validate_records([endpoint_record(state="LIVE VERIFIED")])
    with pytest.raises(LedgerValidationError, match="semantic_evidence"):
        validate_records(
            [
                endpoint_record(
                    state="LIVE VERIFIED",
                    last_verified="2026-09-07",
                    evidence_source="replay: redacted fixture",
                )
            ]
        )
    with pytest.raises(LedgerValidationError, match="last_verified"):
        validate_records(
            [
                endpoint_record(
                    state="LIVE VERIFIED",
                    last_verified="07/09/2026",
                    evidence_source="replay: redacted fixture",
                    semantic_evidence="Returned requested venue identity",
                )
            ]
        )


def test_mutating_methods_and_terms_fail_closed() -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(LedgerValidationError, match="read-only GET"):
            validate_records([endpoint_record(method=method)])

    for term in (
        "booking",
        "reservation",
        "payment",
        "cart",
        "cancel",
        "cancellation",
        "account",
    ):
        with pytest.raises(LedgerValidationError, match="forbidden mutation term"):
            validate_records([endpoint_record(path=f"/v1/{term}/status")])


def test_production_registry_accepts_only_verified_safe_gets() -> None:
    with pytest.raises(ValueError, match="LIVE VERIFIED"):
        EndpointRegistry([Endpoint.from_mapping(endpoint_record())])
    with pytest.raises(ValueError, match="safe_to_replay"):
        EndpointRegistry([live_endpoint(safe_to_replay=False)])
    with pytest.raises(ValueError, match="GET"):
        EndpointRegistry([live_endpoint(method="POST")])

    registry = EndpointRegistry([live_endpoint()])
    assert registry.get("synthetic-discovery").path == "/v1/dineout/discovery"


def test_package_registry_contains_only_verified_runtime_endpoints() -> None:
    registry = EndpointRegistry.from_package_data()

    assert tuple(endpoint.id for endpoint in registry) == (
        "dineout-discovery",
        "dineout-restaurant-detail",
    )
    assert all(
        endpoint.state == "LIVE VERIFIED"
        and endpoint.method == "GET"
        and endpoint.safe_to_replay
        for endpoint in registry
    )


def test_reconciliation_reports_missing_excluded_and_undocumented_routes() -> None:
    documented = endpoint_record()
    inventory = {
        "routes": [
            {
                "method": "GET",
                "host": "api.example.invalid",
                "path": "/v1/dineout/discovery",
                "in_scope": True,
            },
            {
                "method": "GET",
                "host": "api.example.invalid",
                "path": "/v1/dineout/details",
                "in_scope": True,
            },
            {
                "method": "POST",
                "host": "api.example.invalid",
                "path": "/v1/booking/create",
                "in_scope": False,
                "exclusion_reason": "Booking mutation is outside read-only scope",
            },
        ]
    }

    report = reconcile_inventory([documented], inventory)

    assert report.missing == (("GET", "api.example.invalid", "/v1/dineout/details"),)
    assert report.excluded == (("POST", "api.example.invalid", "/v1/booking/create"),)
    assert report.undocumented == ()

    report = reconcile_inventory([documented], {"routes": []})
    assert report.undocumented == (
        ("GET", "api.example.invalid", "/v1/dineout/discovery"),
    )


def test_endpoint_json_requires_one_record_subsection(tmp_path: Path) -> None:
    record = endpoint_record()
    orphan = tmp_path / "orphan.md"
    orphan.write_text(
        "# Ledger\n\n```endpoint-json\n" + json.dumps(record) + "\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerValidationError, match="orphan"):
        parse_endpoint_blocks(orphan)

    duplicate = tmp_path / "duplicate.md"
    duplicate.write_text(
        "# Ledger\n\n### one\n\n```endpoint-json\n"
        + json.dumps(record)
        + "\n```\n\n```endpoint-json\n"
        + json.dumps(endpoint_record(id="second"))
        + "\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerValidationError, match="exactly one"):
        parse_endpoint_blocks(duplicate)


def test_sensitive_values_are_rejected_across_free_text_metadata() -> None:
    for field, value in (
        ("purpose", "Authorization: Bearer unredactedvalue-value"),
        ("limitations", ["Cookie: session=secret-value"]),
        ("semantic_evidence", "Response returned token: secret-value"),
    ):
        with pytest.raises(LedgerValidationError, match="redacted"):
            validate_records([endpoint_record(**{field: value})])
