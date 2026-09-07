from __future__ import annotations

import pytest

from swiggy.endpoints import Endpoint, EndpointRegistry
from swiggy.errors import UnsafeEndpointError
from swiggy.transport import SwiggyTransport


def live_endpoint(**overrides: object) -> Endpoint:
    values: dict[str, object] = {
        "id": "unsafe-test",
        "method": "GET",
        "host": "api.example.invalid",
        "path": "/v1/dineout",
        "state": "LIVE VERIFIED",
        "auth": "guest",
        "location": "none",
        "pagination": "none",
        "purpose": "Synthetic venue response",
        "allowed_inputs": [],
        "observed_fields": ["venues"],
        "limitations": ["Synthetic only"],
        "evidence_source": "replay: redacted synthetic fixture",
        "semantic_evidence": "Response returned venues for the requested location",
        "last_verified": "2026-09-07",
        "in_scope": True,
        "safe_to_replay": True,
    }
    values.update(overrides)
    return Endpoint.from_mapping(values)


def test_registry_rejects_unverified_and_mutating_routes() -> None:
    with pytest.raises(ValueError):
        SwiggyTransport(registry=EndpointRegistry([live_endpoint(state="CAPTURED")]))
    with pytest.raises(ValueError):
        SwiggyTransport(registry=EndpointRegistry([live_endpoint(method="POST")]))


def test_request_rejects_endpoint_id_not_in_registry() -> None:
    transport = SwiggyTransport(registry=EndpointRegistry([live_endpoint()]))

    with pytest.raises(UnsafeEndpointError, match="not registered"):
        transport.request("missing")


def test_transport_uses_descriptive_user_agent() -> None:
    transport = SwiggyTransport(registry=EndpointRegistry([live_endpoint()]))

    assert transport.user_agent.startswith("swiggy-py/")
    assert "token" not in transport.user_agent.casefold()
