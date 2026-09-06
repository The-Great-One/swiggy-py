# Swiggy Dineout Client Design

**Status:** Approved for implementation planning on 2026-09-06.
**Date:** 2026-09-06
**Repository:** `The-Great-One/swiggy-py`

## 1. Goal

Build an independent, API-key-free Python client and CLI for read-only Swiggy Dineout discovery. The client must increase venue-data coverage relative to District by discovering nearby restaurants and enriching them with details, offers, attributes, reviews, and explainable ranking signals. Its normalized output must be suitable for a later District–Swiggy merger without coupling either provider implementation to the other.

## 2. Scope

Version 1 includes:

- nearby Swiggy Dineout discovery from approved coordinates;
- pagination with provider-internal deduplication;
- restaurant identity, location, cuisines, cost, ratings, hours, menus, facilities, and nightlife attributes when exposed;
- Dineout offers with minimum bill, validity, restrictions, and source evidence;
- available reviews and review timestamps;
- `top-rated`, `new`, `trending`, `offers`, and `nightlife` ranking modes;
- human-readable CLI output and stable JSON output;
- field-level provenance and retrieval timestamps;
- guest-first operation with optional authenticated enrichment;
- one canonical endpoint ledger and one maintained findings log;
- fixture, contract, CLI, security, and opt-in live tests.

## 3. Non-goals

Version 1 does not:

- merge District and Swiggy results;
- automate reservations, bookings, payments, carts, cancellations, or account mutations;
- promise fields Swiggy does not expose;
- infer live music, newness, popularity, or trends without source evidence;
- persist raw authenticated payloads by default;
- bypass provider security controls, certificate pinning, bot challenges, or device attestation;
- scrape food-delivery listings unless a Dineout contract directly depends on shared metadata.

## 4. Approach

Use a hybrid, evidence-driven client:

1. Broad discovery through guest-accessible Swiggy web contracts.
2. Detail enrichment through verified web contracts.
3. Selective app/Dineout endpoints only for fields absent from web and only after a read-only live replay succeeds.
4. Graceful degradation: failed enrichment never discards a valid discovery result.

This provides wide baseline coverage without making ordinary search dependent on fragile application authentication.

## 5. Architecture

```text
swiggy-py/
├── src/swiggy/
│   ├── __init__.py
│   ├── client.py          # public SwiggyClient facade
│   ├── transport.py       # session, headers, retry and rate limiting
│   ├── discovery.py       # nearby Dineout listing and pagination
│   ├── restaurants.py     # restaurant details and attributes
│   ├── offers.py          # Dineout offers and restrictions
│   ├── reviews.py         # reviews and recent-rating evidence
│   ├── location.py        # validated approved location storage/detection
│   ├── models.py          # normalized immutable records
│   ├── provenance.py      # source/evidence metadata
│   ├── ranking.py         # quality, momentum, freshness, offer scoring
│   └── cli.py
├── tests/
├── API_ENDPOINTS.md
└── docs/findings.md
```

`SwiggyClient` coordinates provider-specific modules. Transport and authentication are isolated from parsing. Ranking consumes normalized records only and cannot make network calls.

## 6. Location contract

Coordinate precedence:

1. complete explicit latitude/longitude pair;
2. approved record saved at `~/.swiggy-py/location.json`;
3. browser geolocation permission;
4. actionable error if none is available.

A partial explicit pair is invalid. Persist only latitude, longitude, optional accuracy, source, and approval time. Use atomic replacement and private permissions where supported. Never log coordinates in HTTP debug output by default.

## 7. Endpoint discovery and evidence

Discover contracts in this order:

1. Live browser traffic while searching Dineout, opening details, offers, reviews, menus, and attributes.
2. Current Swiggy frontend JavaScript bundle census and request-construction tracing.
3. Current Android APK static analysis for missing fields and host/Retrofit mappings.
4. Bounded read-only replay with redacted evidence.

Every endpoint belongs in `API_ENDPOINTS.md` with one state:

- `LIVE VERIFIED` — successfully replayed read-only;
- `CAPTURED` — observed from an official client but not independently replayed;
- `STATIC ONLY` — found in code but not invoked;
- `AUTH REQUIRED` — route exists but usable credentials are unavailable;
- `RETIRED/BROKEN` — no longer valid or consistently malformed.

Maintain a discovered-versus-documented set-difference check. No endpoint is promoted based solely on a guessed route or HTTP 200 carrying an error card.

## 8. Authentication

The client is guest-first. Public discovery must work without login whenever Swiggy permits it. Optional session data may enrich reviews or offers but cannot be required for baseline search.

Local session state belongs at `~/.swiggy-py/session.json` with private permissions. Authentication failure falls back to guest-accessible data. Credentials, tokens, cookies, OTPs, account identifiers, and unredacted private payloads never enter Git, fixtures, logs, or documentation.

## 9. Data flow

```text
approved location
  → nearby discovery and bounded pagination
  → provider-internal deduplication
  → bounded parallel detail enrichment
      ├── restaurant details
      ├── offers
      ├── reviews
      └── menu and attributes
  → normalized records with field provenance
  → ranking
  → human CLI or JSON output
```

Parallelism and pagination are bounded. Requests use timeouts, a shared session, rate-limit-aware backoff, and a descriptive user agent. Raw payload retention is opt-in, redacted, and outside Git.

## 10. Normalized records

A venue record includes:

- stable Swiggy venue/restaurant identity;
- name and normalized name;
- coordinates, locality, and display address;
- cuisines and cost for two;
- aggregate rating and rating count;
- operating hours and current availability when explicitly supplied;
- offers with terms and dates;
- menu references/data when available;
- attributes such as bar, live music, rooftop, outdoor seating, dance floor, late-night hours, and similar provider-declared facilities;
- recent-review sample and timestamps;
- retrieval time;
- field-level provenance with endpoint, evidence state, and confidence.

Unknown fields are represented as unavailable, never fabricated. Conflicting values remain visible with provenance rather than being silently overwritten.

## 11. Ranking and trend evidence

Ranking dimensions remain separate:

- `quality`: rating, rating volume, and recent-review distribution;
- `momentum`: recent review frequency relative to an older baseline;
- `freshness`: explicit new/recently listed marker, recent listing/menu update, or new campaign;
- `offer_strength`: usable discount after minimum bill, validity, and exclusions;
- `confidence`: quantity and quality of supporting evidence;
- `distance`: geodesic distance from the approved location.

A venue is never called trending solely because its aggregate rating is high. It needs at least one fresh signal. Output explains the evidence and says `insufficient evidence` when dates/history are unavailable. Ranking formulas are deterministic and fixture-tested.

## 12. CLI

Planned commands:

```bash
swiggy restaurants --radius 15
swiggy restaurant --id <venue-id>
swiggy offers --id <venue-id>
swiggy reviews --id <venue-id> --limit 30
swiggy trending --radius 15
swiggy top-rated --radius 15
swiggy new --radius 15
swiggy nightlife --radius 15
swiggy location detect|show|set|clear
```

All discovery commands support `--json`. Explicit coordinates override the saved location. Output labels absent or low-confidence evidence honestly.

## 13. Failure handling

- Discovery failure returns an actionable provider/transport error.
- Detail failure retains the discovery card and records the missing enrichment.
- Authentication expiry falls back to guest mode.
- Rate limiting uses bounded retry with jitter and then returns partial results.
- Schema drift identifies the endpoint and parser stage without exposing raw private data.
- Empty success, provider error-card, malformed payload, and genuine zero-result states are distinct.
- No destructive endpoint is invoked during discovery or testing.

## 14. Documentation and GitHub maintenance

`API_ENDPOINTS.md` is the sole endpoint source of truth. Each entry records method, host, path, request inputs, purpose, evidence state, authentication, pagination, observed fields, last verification date, and redacted source evidence.

`docs/findings.md` records interesting discoveries, provider quirks, limitations, failed hypotheses, discarded approaches, and implications. It is maintained as a current knowledge document—not a raw activity log.

The public repository uses focused commits, GitHub Actions for deterministic tests/lint/packaging, issue tracking for endpoint drift, and secret/local-path scans before every push. Fixtures are synthetic or rigorously redacted.

## 15. Testing

- Unit fixtures: discovery, pagination, details, offers, reviews, menus, missing fields, duplicates, auth expiry, rate limiting, and schema drift.
- Contract tests: stable identity, provenance, valid timestamps, absence reasons, and no secret fields.
- Ranking tests: deterministic scores and no unsupported trend claims.
- CLI tests: human and JSON output, location precedence, invalid arguments, and partial results.
- Security tests: private file permissions, atomic writes, redaction, and non-mutating endpoint allowlist.
- Opt-in live tests: `SWIGGY_LIVE=1 pytest tests/test_smoke.py`; small, read-only, bounded sample only.

## 16. Future District–Swiggy merger contract

The later aggregator will match venues using normalized name, coordinates, locality/address, and phone when available. Provider IDs are never cross-provider identities. It will retain field-level source attribution and conflicts, calculate match confidence, and expose source coverage. This project does not implement that merger in version 1.

## 17. Acceptance criteria

Version 1 is complete when it can:

1. Discover nearby Dineout venues around the approved Gurugram location.
2. Paginate without duplicate Swiggy cards.
3. Fetch available details, offers, attributes, reviews, and menu data.
4. Produce normalized JSON with retrieval and field provenance.
5. Rank top-rated, new, trending, offers, and nightlife results deterministically.
6. Explain every trending classification with fresh evidence.
7. Pass fixture, contract, CLI, security, lint, package, and opt-in live smoke gates.
8. Reconcile every discovered endpoint against `API_ENDPOINTS.md`.
9. Keep interesting findings and limitations current in `docs/findings.md`.
10. Remain structurally ready for a later District–Swiggy aggregator.
