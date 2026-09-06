# swiggy-py

Design-stage unofficial Python client for read-only Swiggy Dineout discovery.

The first release will discover nearby Dineout venues and enrich them with restaurant details, offers, attributes, reviews, and evidence-backed ranking signals. It is intentionally a separate client from [`zomato-py`](https://github.com/The-Great-One/zomato-py); a later provider-neutral aggregator will merge both sources for broader coverage.

## Current status

Architecture approved; implementation has not started. See the canonical design:

- [`docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md`](docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md)
- [`API_ENDPOINTS.md`](API_ENDPOINTS.md) — endpoint evidence ledger
- [`docs/findings.md`](docs/findings.md) — interesting discoveries, limitations, and discarded paths

## Safety and provenance

- Read-only discovery only; no booking, payment, reservation, cart, or account mutation.
- Guest-first operation; optional authentication may enrich results but must not be required for public discovery.
- No credentials, cookies, phone numbers, private payloads, or unredacted captures are committed.
- Every normalized field carries source/evidence provenance.

## License

MIT
