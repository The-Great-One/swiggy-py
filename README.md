# swiggy-py

Unofficial Python client for read-only Swiggy Dineout discovery.

Discovers nearby Dineout venues and enriches them with restaurant details, offers, attributes, reviews, and evidence-backed ranking signals. It is a separate client from [`zomato-py`](https://github.com/The-Great-One/zomato-py); a later provider-neutral aggregator will merge both sources for broader coverage.

## Install

```bash
pip install swiggy-py
```

## Quick start

```bash
# Discover nearby restaurants
swiggy restaurants --latitude 28.4595 --longitude 77.0266 --limit 10

# JSON output with provenance
swiggy restaurants --latitude 28.4595 --longitude 77.0266 --json

# Save a location for reuse
swiggy location set --latitude 28.4595 --longitude 77.0266
swiggy restaurants --limit 10

# Restaurant details
swiggy restaurant --id 302252

# Ranking by mode
swiggy trending --limit 10
swiggy top-rated --limit 10
swiggy nightlife --limit 10
```

## Features

- **Guest-first discovery** — no login required for public Dineout venue discovery
- **Server-rendered parsing** — extracts `__NEXT_DATA__` from Swiggy's HTML responses
- **Field-level provenance** — every normalized field carries source and evidence state
- **Explainable ranking** — quality, momentum, freshness, offers, nightlife, confidence, and distance as separate components; `insufficient evidence` rather than inferred trends
- **Bounded pagination** — capped pages, cursor deduplication, stable-ID deduplication
- **Privacy hardening** — centralized redaction, atomic `0600` session storage, fail-closed public-tree scanner
- **Read-only** — no booking, payment, reservation, cart, or account mutations

## Architecture

- `src/swiggy/transport.py` — bounded HTTP transport with `__NEXT_DATA__` extraction, semantic validation, retry/backoff
- `src/swiggy/discovery.py` — pure parsing, widget-card normalization, bounded pagination, deduplication
- `src/swiggy/restaurants.py` — restaurant detail/menu/facilities parser
- `src/swiggy/offers.py` — offer parser
- `src/swiggy/reviews.py` — review parser
- `src/swiggy/ranking.py` — explainable ranking with Bayesian quality and evidence limitations
- `src/swiggy/client.py` — `SwiggyClient` facade with discovery, enrichment, and ranking
- `src/swiggy/cli.py` — Typer CLI
- `src/swiggy/redaction.py` — centralized `redact()` and `redact_text()`
- `src/swiggy/session.py` — `SessionStore` with atomic write, `0600` permissions
- `src/swiggy/location.py` — deterministic location resolution and persistence
- `scripts/check_public_tree.py` — fail-closed privacy scanner

## Safety and provenance

- Read-only discovery only; no booking, payment, reservation, cart, or account mutation.
- Guest-first operation; optional authentication may enrich results but must not be required for public discovery.
- No credentials, cookies, phone numbers, private payloads, or unredacted captures are committed.
- Every normalized field carries source/evidence provenance.

## Documentation

- [`API_ENDPOINTS.md`](API_ENDPOINTS.md) — endpoint evidence ledger
- [`docs/findings.md`](docs/findings.md) — interesting discoveries, limitations, and discarded paths

## License

MIT