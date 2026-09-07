from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
import respx

from swiggy.endpoints import EndpointRegistry
from swiggy.errors import ProviderResponseError, UnsafeEndpointError
from swiggy.transport import SwiggyTransport

HTML_OK = (
    "<html><script>cards nextOffset /restaurants/ "
    "Flat 20% off on pre-booking</script></html>"
)


def registry() -> EndpointRegistry:
    return EndpointRegistry.from_package_data()


def test_verified_html_endpoint_returns_text_and_optional_json() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://www.swiggy.com/dineout").mock(
            return_value=httpx.Response(200, text=HTML_OK)
        )
        transport = SwiggyTransport(registry=registry())

        response = transport.request("dineout-discovery")

    assert response.status_code == 200
    assert response.text == HTML_OK
    assert response.json_payload is None
    assert response.endpoint_id == "dineout-discovery"


def test_detail_path_parameters_are_encoded_and_validated() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(
            "https://www.swiggy.com/restaurants/delhi/connaught-place/farzi-cafe-302252/dineout"
        ).mock(
            return_value=httpx.Response(
                200, text="restaurantId offers menu amenities hours rating"
            )
        )
        transport = SwiggyTransport(registry=registry())

        response = transport.request(
            "dineout-restaurant-detail",
            path_params={
                "city": "delhi",
                "area": "connaught-place",
                "name": "farzi-cafe-302252",
            },
        )

    assert response.status_code == 200


def test_unknown_path_parameter_is_rejected_before_network() -> None:
    transport = SwiggyTransport(registry=registry())

    with pytest.raises(UnsafeEndpointError, match="path parameter"):
        transport.request(
            "dineout-restaurant-detail", path_params={"city": "delhi", "bad": "x"}
        )


def test_semantic_error_card_is_rejected_even_on_http_200() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://www.swiggy.com/dineout").mock(
            return_value=httpx.Response(200, text="login required error fallback")
        )
        transport = SwiggyTransport(registry=registry())

        with pytest.raises(ProviderResponseError, match="semantic"):
            transport.request("dineout-discovery")


def test_rate_limit_retries_are_bounded_and_use_retry_after() -> None:
    sleeps: list[float] = []
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://www.swiggy.com/dineout")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(503),
            httpx.Response(200, text=HTML_OK),
        ]
        transport = SwiggyTransport(
            registry=registry(),
            max_retries=2,
            sleeper=sleeps.append,
            jitter=lambda _: 0.0,
        )

        response = transport.request("dineout-discovery")

    assert response.status_code == 200
    assert sleeps == [2.0, 2.0]


def test_auth_expiry_falls_back_to_guest_request() -> None:
    seen_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("Authorization"))
        if len(seen_headers) == 1:
            return httpx.Response(401)
        return httpx.Response(200, text=HTML_OK)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://www.swiggy.com/dineout").mock(side_effect=handler)
        transport = SwiggyTransport(
            registry=registry(), session_headers={"authorization": "Bearer test-value"}
        )

        response = transport.request("dineout-discovery")

    assert response.status_code == 200
    assert seen_headers == ["Bearer test-value", None]


def test_transport_exception_does_not_leak_session_header() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get("https://www.swiggy.com/dineout").mock(
            side_effect=httpx.ConnectError("Bearer test-value")
        )
        transport = SwiggyTransport(
            registry=registry(), session_headers={"authorization": "Bearer test-value"}
        )

        with pytest.raises(Exception) as caught:
            transport.request("dineout-discovery")

    assert "Bearer test-value" not in str(caught.value)
    assert "Bearer [REDACTED]" in str(caught.value)


def test_auth_fallback_does_not_consume_zero_retry_budget() -> None:
    seen_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("Authorization"))
        return httpx.Response(401 if len(seen_headers) == 1 else 200, text=HTML_OK)

    with respx.mock(assert_all_called=True) as router:
        router.get("https://www.swiggy.com/dineout").mock(side_effect=handler)
        transport = SwiggyTransport(
            registry=registry(),
            max_retries=0,
            session_headers={"authorization": "Bearer test-value"},
        )
        response = transport.request("dineout-discovery")

    assert response.status_code == 200
    assert seen_headers == ["Bearer test-value", None]


def test_retry_after_http_date_is_bounded() -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=5)
    response = httpx.Response(429, headers={"Retry-After": format_datetime(retry_at)})

    delay = SwiggyTransport._retry_after(response)

    assert 0.0 < delay <= 5.0
