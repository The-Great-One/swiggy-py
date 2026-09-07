from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from swiggy import __version__
from swiggy.endpoints import Endpoint, EndpointRegistry
from swiggy.errors import ProviderResponseError, TransportError, UnsafeEndpointError

_PATH_PARAMETER = re.compile(r"\{([a-zA-Z][a-zA-Z0-9_]*)\}")
_SAFE_RESPONSE_HEADERS = frozenset(
    {"content-type", "content-length", "etag", "last-modified", "cache-control"}
)
_BLOCKED_RESPONSE = re.compile(
    r"(?i)(?:login\\s+required|sign[ -]?in\\s+to\\s+continue|"
    r"unauthorized|forbidden|error\\s+fallback)"
)


@dataclass(frozen=True, slots=True)
class TransportResponse:
    endpoint_id: str
    status_code: int
    headers: Mapping[str, str]
    text: str
    json_payload: object | None


class SwiggyTransport:
    """Bounded, allowlisted transport for semantically verified read-only routes."""

    def __init__(
        self,
        *,
        registry: EndpointRegistry | None = None,
        client: httpx.Client | None = None,
        max_retries: int = 2,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[float], float] | None = None,
        session_headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.registry = registry or EndpointRegistry.from_package_data()
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._owns_client = client is None
        self.max_retries = max(0, max_retries)
        self.sleeper = sleeper
        self.jitter = jitter or (lambda upper: random.uniform(0.0, upper))
        self.session_headers = dict(session_headers or {})
        self.user_agent = user_agent or f"swiggy-py/{__version__}"
        self.timeout = timeout

    def request(
        self,
        endpoint_id: str,
        *,
        path_params: Mapping[str, str] | None = None,
        query_params: Mapping[str, str] | None = None,
    ) -> TransportResponse:
        try:
            endpoint = self.registry.get(endpoint_id)
        except KeyError as error:
            raise UnsafeEndpointError(
                f"endpoint {endpoint_id!r} is not registered for runtime use"
            ) from error
        path = self._render_path(endpoint, path_params or {})
        params = self._validate_query_params(endpoint, query_params or {})
        scheme = "https"
        url = f"{scheme}://{endpoint.host}{path}"
        headers = {"User-Agent": self.user_agent, **self.session_headers}
        response = self._request_with_retries(
            endpoint,
            url,
            params=params,
            headers=headers,
        )
        self._validate_semantics(endpoint, response)
        payload: object | None = None
        if "application/json" in response.headers.get("content-type", "").casefold():
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as error:
                raise ProviderResponseError(
                    f"endpoint {endpoint.id!r} returned invalid JSON"
                ) from error
        safe_headers = {
            key: value
            for key, value in response.headers.items()
            if key.casefold() in _SAFE_RESPONSE_HEADERS
        }
        return TransportResponse(
            endpoint_id=endpoint.id,
            status_code=response.status_code,
            headers=safe_headers,
            text=response.text,
            json_payload=payload,
        )

    def _render_path(self, endpoint: Endpoint, values: Mapping[str, str]) -> str:
        names = tuple(_PATH_PARAMETER.findall(endpoint.path))
        unexpected = set(values) - set(names)
        missing = set(names) - set(values)
        if unexpected:
            raise UnsafeEndpointError(
                f"unexpected path parameter(s) for {endpoint.id!r}: "
                f"{sorted(unexpected)}"
            )
        if missing:
            raise UnsafeEndpointError(
                f"missing path parameter(s) for {endpoint.id!r}: {sorted(missing)}"
            )
        return _PATH_PARAMETER.sub(
            lambda match: quote(values[match.group(1)], safe=""), endpoint.path
        )

    def _validate_query_params(
        self, endpoint: Endpoint, values: Mapping[str, str]
    ) -> dict[str, str]:
        unexpected = set(values) - set(endpoint.allowed_inputs)
        if unexpected:
            raise UnsafeEndpointError(
                f"unexpected query parameter(s) for {endpoint.id!r}: "
                f"{sorted(unexpected)}"
            )
        return dict(values)

    def _request_with_retries(
        self,
        endpoint: Endpoint,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> httpx.Response:
        request_headers = dict(headers)
        auth_fallback_used = False
        auth_key = next(
            (
                key
                for key, value in request_headers.items()
                if key.casefold() == "authorization" and value
            ),
            None,
        )
        attempt = 0
        while attempt <= self.max_retries:
            try:
                response = self._client.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=self.timeout,
                )
            except httpx.HTTPError as error:
                if attempt >= self.max_retries:
                    raise TransportError(
                        f"GET {endpoint.id!r} failed after bounded retries: "
                        f"{type(error).__name__}"
                    ) from None
                self.sleeper(self.jitter(min(8.0, 2.0**attempt)))
                attempt += 1
                continue
            if (
                response.status_code == 401
                and auth_key is not None
                and not auth_fallback_used
            ):
                response.close()
                request_headers.pop(auth_key, None)
                auth_fallback_used = True
                continue
            if response.status_code in {429, 502, 503}:
                if attempt >= self.max_retries:
                    raise TransportError(
                        f"GET {endpoint.id!r} returned retryable HTTP "
                        f"{response.status_code}"
                    )
                delay = self._retry_after(response)
                if delay == 0.0:
                    delay = min(8.0, 2.0**attempt)
                response.close()
                self.sleeper(delay + self.jitter(0.25))
                attempt += 1
                continue
            if response.status_code >= 400:
                response.close()
                raise ProviderResponseError(
                    f"GET {endpoint.id!r} returned HTTP {response.status_code}"
                )
            return response
        raise TransportError(f"GET {endpoint.id!r} exhausted retry policy")

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After", "0")
        try:
            delay = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return 0.0
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            delay = (retry_at - datetime.now(UTC)).total_seconds()
        return max(0.0, min(30.0, delay))

    @staticmethod
    def _validate_semantics(endpoint: Endpoint, response: httpx.Response) -> None:
        text = response.text.casefold()
        if _BLOCKED_RESPONSE.search(text):
            raise ProviderResponseError(
                f"endpoint {endpoint.id!r} returned a login/error semantic response"
            )
        aliases = {
            "restaurant_links": "/restaurants/",
            "next_offset": "nextoffset",
            "offer_text": "off on pre-booking",
            "restaurant_id": "restaurantid",
            "rating_count": "ratings",
        }
        missing = [
            field
            for field in endpoint.observed_fields
            if aliases.get(field, field).casefold() not in text
        ]
        if missing:
            raise ProviderResponseError(
                f"endpoint {endpoint.id!r} failed semantic field check: "
                f"{', '.join(missing)}"
            )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SwiggyTransport:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
