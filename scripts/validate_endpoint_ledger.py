#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from swiggy.endpoints import (
    LedgerValidationError,
    find_handwritten_endpoint_literals,
    generated_registry_payload,
    parse_endpoint_blocks,
    reconcile_inventory,
    validate_records,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "API_ENDPOINTS.md"
DEFAULT_INVENTORY = ROOT / "tests/fixtures/route_inventory.json"
DEFAULT_GENERATED = ROOT / "src/swiggy/_endpoint_registry.json"
DEFAULT_SOURCE = ROOT / "src/swiggy"


def _serialized(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def validate(
    *,
    ledger_path: Path,
    inventory_path: Path,
    generated_path: Path,
    source_path: Path,
    write_generated: bool,
    check_generated: bool,
) -> int:
    records = parse_endpoint_blocks(ledger_path)
    validate_records(records)
    inventory_value = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(inventory_value, dict):
        raise LedgerValidationError("route inventory must be a JSON object")
    report = reconcile_inventory(records, inventory_value)
    payload = generated_registry_payload(records)
    expected = _serialized(payload)

    if write_generated:
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.write_text(expected, encoding="utf-8")
    if check_generated:
        try:
            actual = generated_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise LedgerValidationError(
                f"generated registry is missing: {generated_path}"
            ) from error
        if actual != expected:
            raise LedgerValidationError(
                "generated registry differs from API_ENDPOINTS.md; "
                "run with --write-generated"
            )

    violations = find_handwritten_endpoint_literals(source_path)
    if violations:
        details = ", ".join(
            f"{item.path}:{item.line} ({item.kind})" for item in violations
        )
        raise LedgerValidationError(
            f"handwritten production endpoint literals: {details}"
        )

    reconciliation = {
        "missing": [list(route) for route in report.missing],
        "excluded": [list(route) for route in report.excluded],
        "undocumented": [list(route) for route in report.undocumented],
    }
    print(json.dumps(reconciliation, sort_keys=True))
    if report.missing or report.undocumented:
        raise LedgerValidationError("endpoint ledger reconciliation failed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the endpoint evidence ledger"
    )
    parser.add_argument("--write-generated", action="store_true")
    parser.add_argument("--check-generated", action="store_true")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--generated", type=Path, default=DEFAULT_GENERATED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        return validate(
            ledger_path=args.ledger,
            inventory_path=args.inventory,
            generated_path=args.generated,
            source_path=args.source,
            write_generated=args.write_generated,
            check_generated=args.check_generated,
        )
    except (LedgerValidationError, json.JSONDecodeError) as error:
        parser.exit(1, f"endpoint ledger validation failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
