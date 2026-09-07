# Swiggy Dineout Client Implementation Plan

> **For Hermes:** Use `subagent-driven-development` to implement this plan task-by-task. Use `hermes-role-routing` for reconnaissance, multi-file implementation, independent review, and authorized commit/push. Every network contract must be evidenced before production code invokes it.

**Goal:** Build and publish a tested, API-key-free, read-only Python client and CLI that discovers and enriches nearby Swiggy Dineout venues and ranks them with explicit evidence.

**Architecture:** A guest-first `SwiggyClient` facade coordinates bounded HTTP transport, provider-specific parsers, immutable normalized models, and pure deterministic ranking. Endpoint contracts are promoted only after official-client capture or static discovery plus semantically successful read-only replay. Missing enrichment remains attached as structured absence/failure metadata instead of deleting a discovered venue.

**Tech Stack:** Python 3.11+, `uv`, `httpx`, Pydantic 2, Typer, pytest, pytest-cov, respx, Ruff, mypy, GitHub Actions.

**Authoritative design:** `docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md`

---

## Scope boundaries

The implementation includes Dineout discovery, details, offers, reviews, menu/facility attributes, normalized JSON, provenance, location handling, evidence-backed ranking, documentation reconciliation, and opt-in read-only smoke tests.

It does **not** merge District data, mutate Swiggy state, book tables, create carts, pay, cancel, bypass security controls, promise unavailable fields, or infer trends/newness/nightlife without evidence.

## Non-negotiable execution rules

1. Do not write a production URL until it has an entry in `API_ENDPOINTS.md`.
2. Do not promote an endpoint to `LIVE VERIFIED` on HTTP status alone; assert expected semantic fields and requested-location identity.
3. Invoke only explicitly allowlisted `GET`/read-only contracts. A discovered mutation route may be documented as excluded but never replayed.
4. Never commit raw HAR files, cookies, tokens, account identifiers, phone numbers, exact private coordinates, device IDs, or unredacted authenticated payloads.
5. Use synthetic coordinates in fixtures and docs. Live tests obtain coordinates only from explicit flags/environment or approved local storage.
6. Every ranking result must expose component scores, evidence, and confidence. `trending=true` requires a fresh signal.
7. After each task, run its focused gate and commit only the listed paths. Push after each completed execution session.

## Planned repository shape

```text
src/swiggy/
├── __init__.py
├── cli.py
├── client.py
├── discovery.py
├── endpoints.py
├── errors.py
├── location.py
├── models.py
├── offers.py
├── provenance.py
├── ranking.py
├── restaurants.py
├── reviews.py
└── transport.py
scripts/
├── extract_bundle_routes.py
├── sanitize_capture.py
└── validate_endpoint_ledger.py
tests/
├── contract/
├── fixtures/
├── integration/
├── security/
└── unit/
```

---

### Task 1: Establish the Python package and deterministic quality gates

**Objective:** Create an installable package, CLI entry point, tool configuration, and CI before behavior is added.

**Files:**
- Create: `pyproject.toml`
- Create: `src/swiggy/__init__.py`
- Create: `src/swiggy/cli.py`
- Create: `tests/unit/test_package.py`
- Create: `.github/workflows/ci.yml`
- Modify: `.gitignore`

**Step 1: Write the failing package smoke test**

```python
from typer.testing import CliRunner

from swiggy import __version__
from swiggy.cli import app


def test_package_and_cli_are_importable() -> None:
    assert __version__ == "0.1.0"
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "swiggy-py 0.1.0"
```

**Step 2: Run the test and verify RED**

Run: `uv run pytest tests/unit/test_package.py -q`

Expected: failure because the package/configuration does not exist.

**Step 3: Add the minimal package**

Configure:

- build backend: `hatchling`;
- package source: `src/swiggy`;
- runtime dependencies: `httpx>=0.27,<1`, `pydantic>=2.8,<3`, `typer>=0.12,<1`;
- dev dependencies: pytest, pytest-cov, respx, Ruff, mypy;
- console script: `swiggy = "swiggy.cli:app"`;
- Ruff and mypy strict checks for `src` and `tests`.

Implement `__version__ = "0.1.0"` and only `--version` in the initial Typer app.

CI must run on macOS-independent Ubuntu with Python 3.11 and 3.13:

```bash
uv sync --all-groups --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=swiggy --cov-report=term-missing
uv build
```

**Step 4: Verify GREEN and artifacts**

Run:

```bash
uv lock
uv sync --all-groups --locked
uv run pytest tests/unit/test_package.py -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv build
```

Expected: all commands pass and both wheel and sdist are created.

**Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/swiggy/__init__.py src/swiggy/cli.py tests/unit/test_package.py .github/workflows/ci.yml .gitignore
git commit -m "build: scaffold swiggy-py package"
```

---

### Task 2: Define immutable normalized records and provenance

**Objective:** Lock the provider-neutral data contract before writing any parser.

**Files:**
- Create: `src/swiggy/provenance.py`
- Create: `src/swiggy/models.py`
- Create: `src/swiggy/errors.py`
- Create: `tests/unit/test_models.py`
- Create: `tests/contract/test_venue_contract.py`

**Step 1: Write failing contract tests**

Cover:

- frozen Pydantic models;
- timezone-aware retrieval timestamps;
- stable Swiggy identity separate from cross-provider identity;
- explicit absence reasons;
- field-level source records;
- offers with optional restrictions/validity;
- conflicts retaining both source values;
- JSON serialization without secrets.

Representative assertion:

```python
assert venue.provenance["rating"].endpoint_id == "dineout-discovery"
assert venue.provenance["rating"].evidence_state == EvidenceState.LIVE_VERIFIED
assert venue.model_dump(mode="json")["provider"] == "swiggy"
```

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_models.py tests/contract/test_venue_contract.py -q`

Expected: import failures.

**Step 3: Implement minimal typed models**

Create:

- `EvidenceState` enum;
- `SourceEvidence`, `UnavailableField`, `FieldConflict`;
- `Coordinates`, `OperatingHours`, `Offer`, `ReviewSample`, `MenuReference`;
- `VenueAttributes`, `VenueRecord`, `EnrichmentFailure`;
- public exceptions: `SwiggyError`, `ConfigurationError`, `TransportError`, `ProviderResponseError`, `SchemaDriftError`, `UnsafeEndpointError`.

Use `ConfigDict(frozen=True, extra="forbid")`. Unknown data must be `None` plus an absence reason where the distinction matters; never use invented placeholders.

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/unit/test_models.py tests/contract/test_venue_contract.py -q
uv run mypy src/swiggy/models.py src/swiggy/provenance.py src/swiggy/errors.py
```

**Step 5: Commit**

```bash
git add src/swiggy/models.py src/swiggy/provenance.py src/swiggy/errors.py tests/unit/test_models.py tests/contract/test_venue_contract.py
git commit -m "feat: define normalized venue contracts"
```

---

### Task 3: Make the endpoint ledger machine-checkable and fail closed

**Objective:** Turn `API_ENDPOINTS.md` into the sole documented endpoint authority while testing coverage and safety.

**Files:**
- Create: `src/swiggy/endpoints.py`
- Generate: `src/swiggy/_endpoint_registry.json`
- Create: `scripts/validate_endpoint_ledger.py`
- Create: `tests/fixtures/route_inventory.json`
- Create: `tests/contract/test_endpoint_ledger.py`
- Create: `tests/contract/test_endpoint_source_integrity.py`
- Modify: `API_ENDPOINTS.md`
- Modify: `pyproject.toml`

**Step 1: Define the embedded endpoint-record format**

Each endpoint section in `API_ENDPOINTS.md` contains one fenced `endpoint-json` object with:

```json
{
  "id": "stable-kebab-id",
  "method": "GET",
  "host": "example.invalid",
  "path": "/redacted/template/{id}",
  "state": "STATIC ONLY",
  "auth": "guest|optional|required",
  "location": "none|query|headers|body",
  "pagination": "none|offset|cursor|unknown",
  "purpose": "short description",
  "allowed_inputs": ["named-input-only"],
  "observed_fields": ["semantic-field"],
  "limitations": ["known limitation"],
  "evidence_source": "redacted capture/static source reference",
  "semantic_evidence": "expected successful-response meaning",
  "last_verified": null,
  "in_scope": true,
  "safe_to_replay": false
}
```

Do not add guessed Swiggy URLs in this task. The example uses `.invalid` and is marked as schema documentation, not an endpoint entry.

**Step 2: Write failing tests**

Test that:

- every captured/static in-scope route fixture has one ledger record;
- duplicate IDs and `(method, host, path)` tuples fail;
- production registries reject non-`LIVE VERIFIED` endpoints;
- replay allowlist accepts only `GET` plus `safe_to_replay=true`;
- forbidden mutation terms/methods fail closed;
- every record contains allowed inputs, observed fields, limitations, and redacted evidence source;
- every `LIVE VERIFIED` entry has a date and non-empty semantic evidence note;
- an AST/source scan rejects handwritten production host, path, or URL literals in every Python module; endpoint values may exist only in the generated registry derived from `API_ENDPOINTS.md`.

**Step 3: Verify RED**

Run: `uv run pytest tests/contract/test_endpoint_ledger.py -q`

**Step 4: Implement the parser and validator**

`scripts/validate_endpoint_ledger.py` parses only fenced `endpoint-json` blocks. `--write-generated` deterministically produces `src/swiggy/_endpoint_registry.json`; `--check-generated` fails when it differs from `API_ENDPOINTS.md`. This generated package data is shipped in wheels, while Markdown remains the sole human-edited authority. `EndpointRegistry.from_package_data()` loads the generated resource through `importlib.resources`; runtime code resolves endpoints by stable ID, never by scattered URL literals. The validator also compares ledger records with the redacted route inventory and prints explicit missing/excluded sets.

**Step 5: Verify GREEN**

Run:

```bash
uv run python scripts/validate_endpoint_ledger.py --write-generated
uv run python scripts/validate_endpoint_ledger.py --check-generated
uv run pytest tests/contract/test_endpoint_ledger.py tests/contract/test_endpoint_source_integrity.py -q
```

Expected: zero undocumented in-scope routes, no replayable endpoint yet, no endpoint-literal bypass, and installed package data exactly matches the Markdown ledger.

**Step 6: Commit**

```bash
git add API_ENDPOINTS.md pyproject.toml src/swiggy/endpoints.py src/swiggy/_endpoint_registry.json scripts/validate_endpoint_ledger.py tests/fixtures/route_inventory.json tests/contract/test_endpoint_ledger.py tests/contract/test_endpoint_source_integrity.py
git commit -m "feat: enforce endpoint evidence ledger"
```

---

### Task 4: Build privacy-preserving reconnaissance utilities

**Objective:** Provide deterministic tools for extracting candidate routes and sanitizing captures without committing private traffic.

**Files:**
- Create: `scripts/extract_bundle_routes.py`
- Create: `scripts/sanitize_capture.py`
- Create: `tests/security/test_sanitize_capture.py`
- Create: `tests/unit/test_extract_bundle_routes.py`
- Create: `tests/fixtures/synthetic_capture.json`
- Modify: `.gitignore`
- Modify: `docs/findings.md`

**Step 1: Write failing sanitizer and extraction tests**

Fixtures must prove removal/hash replacement of:

- Cookie/Authorization headers;
- token-like query/body fields;
- phone/email/account/device identifiers;
- precise coordinate values;
- request/response bodies outside an explicit field allowlist.

Bundle extraction tests must return candidate `(method, host, path)` tuples without executing them.

**Step 2: Verify RED**

Run: `uv run pytest tests/security/test_sanitize_capture.py tests/unit/test_extract_bundle_routes.py -q`

**Step 3: Implement utilities**

- `sanitize_capture.py` reads a local HAR/JSON capture, emits a redacted route inventory, and refuses to overwrite the input.
- `extract_bundle_routes.py` reads already-downloaded JS text, extracts candidate hosts/path templates, and labels every result `STATIC ONLY`.
- Neither script performs authenticated network calls.
- Ignore `captures/`, `raw/`, `*.har`, APKs, and generated raw payloads.

**Step 4: Add a findings entry**

Document the sanitization boundary, what evidence is retained, and why raw captures stay outside Git.

**Step 5: Verify GREEN and a synthetic leak scan**

Run:

```bash
uv run pytest tests/security/test_sanitize_capture.py tests/unit/test_extract_bundle_routes.py -q
uv run python scripts/sanitize_capture.py tests/fixtures/synthetic_capture.json --output /tmp/swiggy-routes.json
```

Expected: output contains route structure but none of the seeded secret or personal values.

**Step 6: Commit**

```bash
git add scripts/extract_bundle_routes.py scripts/sanitize_capture.py tests/security/test_sanitize_capture.py tests/unit/test_extract_bundle_routes.py tests/fixtures/synthetic_capture.json .gitignore docs/findings.md
git commit -m "feat: add safe endpoint reconnaissance tools"
```

---

### Task 5: Discover and semantically verify current Dineout contracts

**Objective:** Produce the first evidence-backed endpoint ledger before implementing network behavior.

**Files:**
- Modify: `API_ENDPOINTS.md`
- Modify: `docs/findings.md`
- Modify: `tests/fixtures/route_inventory.json`
- Create only after sanitization: `tests/fixtures/contracts/*.json`

**Step 1: Capture official-client behavior read-only**

Using an approved browser session:

1. set a synthetic/testable Gurugram-area location;
2. open Dineout discovery;
3. paginate once;
4. open one venue detail page;
5. inspect offers, reviews, menu, and facilities;
6. save raw capture outside the repository;
7. run `scripts/sanitize_capture.py` before inspecting/committing derived evidence.

Do not book, reserve, add to cart, pay, cancel, submit forms, or replay mutation requests.

**Step 2: Census current frontend bundles**

Download only public frontend assets referenced by the current official page. Run `scripts/extract_bundle_routes.py`. Match static candidates to captured traffic. Label unmatched candidates `STATIC ONLY`.

**Step 3: Use APK analysis only for missing in-scope fields**

If web traffic does not expose required details, statically inspect the current official APK for host/path/request mappings. Do not bypass certificate pinning, attestation, or authentication. Record candidates as `STATIC ONLY` or `AUTH REQUIRED` until independently replayed.

**Step 4: Replay only safe candidates**

For each candidate approved by the endpoint allowlist:

- use a bounded timeout and descriptive user agent;
- verify HTTP status;
- assert expected Dineout semantic fields;
- assert the requested location/venue identity;
- distinguish true empty results from error cards/login shells;
- redact and minimize a fixture containing only parser-relevant fields.

Promote to `LIVE VERIFIED` only if all checks pass.

**Step 5: Reconcile documentation**

For every discovered route, either add an endpoint record or an explicit exclusion reason. Add findings for identifier relationships, pagination semantics, auth requirements, review timestamps, error envelopes, and useful limitations.

**Step 6: Run documentation/security gates**

```bash
uv run python scripts/validate_endpoint_ledger.py
uv run pytest tests/contract/test_endpoint_ledger.py tests/security -q
```

Expected: all in-scope captured routes are documented; fixtures contain no secret/local/private-coordinate patterns; at least baseline discovery has a usable read-only contract or the task ends with an explicit blocker instead of guessed implementation.

**Step 7: Commit**

```bash
git add API_ENDPOINTS.md docs/findings.md tests/fixtures/route_inventory.json tests/fixtures/contracts
git commit -m "docs: record verified Dineout endpoint contracts"
```

---

### Task 6: Implement bounded transport and semantic response validation

**Objective:** Build a shared client that can invoke only ledger-approved routes and classify transport/provider failures accurately.

**Files:**
- Create: `src/swiggy/transport.py`
- Create: `tests/unit/test_transport.py`
- Create: `tests/security/test_transport_allowlist.py`

**Step 1: Write failing tests with `respx`**

Cover:

- default connect/read/write/pool timeouts;
- descriptive non-secret user agent;
- bounded retry for 429/502/503 with `Retry-After` and jitter injection;
- no retry for schema/auth errors;
- guest fallback after optional auth failure;
- redacted exceptions;
- semantic rejection of error cards and login shells;
- hard rejection of unregistered, non-verified, non-GET, or unsafe routes.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_transport.py tests/security/test_transport_allowlist.py -q`

**Step 3: Implement minimal transport**

`SwiggyTransport` receives an `httpx.Client`, `EndpointRegistry`, retry policy, sleep function, and optional redacted session provider. It resolves a stable endpoint ID, builds the URL from ledger data, validates allowed input names, performs the request, and returns a typed response envelope containing status, headers, text, and an optional decoded JSON payload. HTML/Next-data contracts remain text until their provider-specific parser extracts the data. Every response passes endpoint-specific semantic guards before the envelope is returned.

No Python module, including `endpoints.py`, may contain handwritten production Swiggy host, path, or URL literals. `endpoints.py` constructs requests only from validated fields loaded from the generated registry; that generated artifact is the only runtime copy of values authored in `API_ENDPOINTS.md`.

**Step 4: Verify GREEN**

```bash
uv run pytest tests/unit/test_transport.py tests/security/test_transport_allowlist.py -q
uv run mypy src/swiggy/transport.py src/swiggy/endpoints.py
```

**Step 5: Commit**

```bash
git add src/swiggy/transport.py tests/unit/test_transport.py tests/security/test_transport_allowlist.py
git commit -m "feat: add safe bounded HTTP transport"
```

---

### Task 7: Implement approved location storage and precedence

**Objective:** Resolve location deterministically while keeping exact coordinates out of logs and Git.

**Files:**
- Create: `src/swiggy/location.py`
- Create: `tests/unit/test_location.py`
- Create: `tests/security/test_location_privacy.py`

**Step 1: Write failing tests**

Cover:

- complete explicit pair wins;
- partial explicit pair raises `ConfigurationError` and does not fall through;
- saved approved location is second;
- injected browser detector is third;
- absence returns an actionable error;
- latitude/longitude range validation;
- atomic replacement;
- mode `0600` where supported;
- logs and exceptions omit coordinate values.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_location.py tests/security/test_location_privacy.py -q`

**Step 3: Implement minimal location API**

Use `Path.home() / ".swiggy-py" / "location.json"` by default with an injectable path for tests. Store only latitude, longitude, optional accuracy, source, and approval timestamp. Browser detection must be an optional adapter, not imported by core code.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/test_location.py tests/security/test_location_privacy.py -q`

**Step 5: Commit**

```bash
git add src/swiggy/location.py tests/unit/test_location.py tests/security/test_location_privacy.py
git commit -m "feat: add private approved location storage"
```

---

### Task 8: Parse discovery pages and deduplicate pagination

**Objective:** Convert verified nearby-discovery fixtures into normalized venue cards without duplicates.

**Files:**
- Create: `src/swiggy/discovery.py`
- Create: `tests/unit/test_discovery.py`
- Add/modify: `tests/fixtures/contracts/discovery_*.json`

**Step 1: Write failing parser tests**

Test:

- one valid page;
- legitimate empty result;
- provider error card;
- malformed schema with endpoint/parser context;
- missing optional fields;
- cursor/offset extraction;
- repeated cards across pages;
- stable ID dedupe while preserving first-seen order and richer later fields;
- bounded maximum pages/results;
- provenance for every parsed field.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_discovery.py -q`

**Step 3: Implement pure parser first**

`parse_discovery_page(payload, evidence)` performs no I/O. `DiscoveryService.nearby()` then invokes the verified endpoint through `SwiggyTransport`, stops on no next cursor, repeated cursor, maximum pages, or maximum results, and deduplicates by stable Swiggy ID.

**Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/test_discovery.py -q`

**Step 5: Commit**

```bash
git add src/swiggy/discovery.py tests/unit/test_discovery.py tests/fixtures/contracts/discovery_*.json
git commit -m "feat: add Dineout discovery pagination"
```

---

### Task 9: Parse details, offers, reviews, menus, and facilities independently

**Objective:** Enrich discovery cards through isolated parsers so one schema failure cannot erase other data.

**Files:**
- Create: `src/swiggy/restaurants.py`
- Create: `src/swiggy/offers.py`
- Create: `src/swiggy/reviews.py`
- Create: `tests/unit/test_restaurants.py`
- Create: `tests/unit/test_offers.py`
- Create: `tests/unit/test_reviews.py`
- Add: `tests/fixtures/contracts/detail_*.json`
- Add: `tests/fixtures/contracts/offers_*.json`
- Add: `tests/fixtures/contracts/reviews_*.json`

**Step 1: Write failing detail tests**

Assert parsing and provenance for address/locality, cuisines, cost, coordinates, hours, rating/count, menus, and explicitly declared facilities. Presentation labels count only when the endpoint semantics establish them as venue attributes.

**Step 2: Write failing offer tests**

Assert percentage/flat discounts, minimum bill, cap, applicable dates/times, payment constraints, exclusions, and unusable/expired status. Preserve offer text when structured terms are absent; do not fabricate calculations.

**Step 3: Write failing review tests**

Assert review IDs where present, rating, text excerpt, timezone-aware timestamp, pagination, missing-date representation, and recent sample boundaries.

**Step 4: Verify RED**

Run:

```bash
uv run pytest tests/unit/test_restaurants.py tests/unit/test_offers.py tests/unit/test_reviews.py -q
```

**Step 5: Implement pure parsers and service wrappers**

Each parser receives payload plus source evidence and returns a typed partial result. Service wrappers use endpoint IDs from the registry. Schema errors identify endpoint and parser stage but contain no raw response.

**Step 6: Verify GREEN**

Run the same focused suite and strict mypy for the three modules.

**Step 7: Commit**

```bash
git add src/swiggy/restaurants.py src/swiggy/offers.py src/swiggy/reviews.py tests/unit/test_restaurants.py tests/unit/test_offers.py tests/unit/test_reviews.py tests/fixtures/contracts
git commit -m "feat: add Dineout enrichment parsers"
```

---

### Task 10: Orchestrate partial enrichment through `SwiggyClient`

**Objective:** Expose a stable public facade with bounded concurrency and graceful partial failure.

**Files:**
- Create: `src/swiggy/client.py`
- Modify: `src/swiggy/__init__.py`
- Create: `tests/integration/test_client.py`

**Step 1: Write failing integration tests**

Test that:

- baseline search works in guest mode;
- detail/offers/reviews/menu enrichments merge by stable venue ID;
- one enrichment failure leaves the discovery venue intact;
- failures appear in `enrichment_failures`;
- conflicts retain both values and provenance;
- concurrency and requested result limits are bounded;
- output order is deterministic regardless of completion order;
- client closes owned transports but not injected clients;
- `rank_nearby()` exposes every ranking mode, including offer-strength discovery.

**Step 2: Verify RED**

Run: `uv run pytest tests/integration/test_client.py -q`

**Step 3: Implement the facade**

Public methods:

```python
search_nearby(...)
get_restaurant(venue_id)
get_offers(venue_id)
get_reviews(venue_id, limit=30)
enrich(venues, *, max_workers=4)
rank_nearby(mode, *, radius_km, limit, max_workers=4)
```

Use a small bounded worker pool only for independent enrichment. Keep merge logic deterministic and field-aware.

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/integration/test_client.py -q
uv run mypy src/swiggy/client.py
```

**Step 5: Commit**

```bash
git add src/swiggy/client.py src/swiggy/__init__.py tests/integration/test_client.py
git commit -m "feat: add resilient Swiggy client facade"
```

---

### Task 11: Implement deterministic, explainable ranking

**Objective:** Rank venues without conflating established quality with current momentum.

**Files:**
- Create: `src/swiggy/ranking.py`
- Create: `tests/unit/test_ranking.py`
- Create: `tests/fixtures/ranking_cases.json`
- Modify: `docs/findings.md`

**Step 1: Freeze formulas in tests before implementation**

Define component values on `[0, 100]`:

- `quality`: Bayesian rating using a documented prior plus log-scaled rating volume; recent sentiment may adjust only when a minimum dated sample exists;
- `momentum`: recent dated review rate divided by an older comparable window, clamped and sample-size weighted;
- `freshness`: explicit new/listed/update/campaign evidence with age decay;
- `offer_strength`: effective discount after cap/minimum-bill/validity penalties;
- `confidence`: weighted completeness and evidence-state quality;
- `distance_km`: haversine distance, retained separately rather than hidden in quality.

Tests must prove:

- high-rated but stale venue is not automatically trending;
- recent volume acceleration can qualify with an explanation;
- explicit new marker can qualify with lower confidence;
- undated reviews produce `insufficient evidence`;
- expired offers contribute zero;
- missing data has a neutral/explicit effect, not an invented value;
- tie-breaking is deterministic by confidence, distance, normalized name, then provider ID.

**Step 2: Verify RED**

Run: `uv run pytest tests/unit/test_ranking.py -q`

**Step 3: Implement pure scoring**

Return `RankingResult` containing every component, evidence strings, confidence, and a trend classification/reason. Support `top-rated`, `new`, `trending`, `offers`, and `nightlife` sort modes. Nightlife ranking only uses explicit provider-declared attributes and late-hour evidence.

**Step 4: Document empirical assumptions**

Add current formula rationale and known evidence limitations to `docs/findings.md`. Constants live once in `ranking.py` and are named/documented.

**Step 5: Verify GREEN and determinism**

Run the ranking suite twice with randomized input ordering; expected serialized order is identical.

**Step 6: Commit**

```bash
git add src/swiggy/ranking.py tests/unit/test_ranking.py tests/fixtures/ranking_cases.json docs/findings.md
git commit -m "feat: add explainable venue ranking"
```

---

### Task 12: Deliver human-readable and stable JSON CLI commands

**Objective:** Expose all approved workflows without hiding uncertainty or provenance.

**Files:**
- Modify: `src/swiggy/cli.py`
- Create: `tests/integration/test_cli.py`
- Create: `tests/fixtures/cli_expected/*.json`

**Step 1: Write failing CLI tests**

Cover:

- `restaurants`, `restaurant`, `offers`, `reviews`;
- `trending`, `top-rated`, `new`, `nightlife`;
- `offers --id <venue-id>` for one venue and `offers --radius <km>` for offer-ranked discovery, with mutual-exclusion validation;
- `location set|show|clear|detect`;
- explicit coordinate precedence and partial-pair rejection;
- `--json` stability;
- human labels for unavailable/low-confidence evidence;
- trending explanation display;
- partial enrichment exit behavior;
- invalid IDs/radius/limits;
- no exact coordinate leakage from `location show` unless an explicit reveal flag is used.

**Step 2: Verify RED**

Run: `uv run pytest tests/integration/test_cli.py -q`

**Step 3: Implement commands with dependency injection seams**

CLI commands call `SwiggyClient`; tests inject a fixture-backed client. JSON output uses one versioned top-level schema:

```json
{
  "schema_version": "1",
  "query": {},
  "results": [],
  "partial": false,
  "errors": []
}
```

Human output includes rating count, offer restrictions, evidence/confidence, distance, and why a venue is or is not trending.

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/integration/test_cli.py -q
uv run swiggy --help
uv run swiggy trending --help
```

**Step 5: Commit**

```bash
git add src/swiggy/cli.py tests/integration/test_cli.py tests/fixtures/cli_expected
git commit -m "feat: add Dineout discovery CLI"
```

---

### Task 13: Harden redaction, session storage, and public-repository safety

**Objective:** Prove credentials/private data cannot enter logs, errors, fixtures, or ordinary Git changes.

**Files:**
- Create: `src/swiggy/redaction.py`
- Create: `src/swiggy/session.py`
- Modify: `src/swiggy/transport.py`
- Create: `tests/security/test_redaction.py`
- Create: `tests/security/test_session_storage.py`
- Create: `scripts/check_public_tree.py`
- Modify: `.github/workflows/ci.yml`

**Step 1: Write failing security tests**

Seed synthetic tokens, cookies, emails, phone numbers, device/account IDs, exact coordinates, auth headers, and local absolute paths. Assert absence from:

- log records;
- exception strings/reprs;
- serialized venue output;
- sanitized fixtures;
- generated debug metadata.

Assert session files are atomically written with private permissions and guest fallback does not rewrite valid session data.

**Step 2: Verify RED**

Run: `uv run pytest tests/security -q`

**Step 3: Implement centralized redaction and tree scanner**

All transport logging and diagnostic exceptions use the same redactor. `SessionStore` uses `Path.home() / ".swiggy-py" / "session.json"` by default, accepts an injected path for tests, validates an allowlist of cookie/header fields, performs atomic `0600` writes where supported, never logs values, and exposes read/clear operations without performing login or OTP flows. `check_public_tree.py` scans tracked files only, supports a documented false-positive allowlist, and fails on secret/local-path/private-capture patterns.

**Step 4: Add CI gate**

Run the scanner before tests/build in GitHub Actions.

**Step 5: Verify GREEN**

```bash
uv run pytest tests/security -q
uv run python scripts/check_public_tree.py
```

**Step 6: Commit**

```bash
git add src/swiggy/redaction.py src/swiggy/session.py src/swiggy/transport.py tests/security scripts/check_public_tree.py .github/workflows/ci.yml
git commit -m "security: harden redaction and session handling"
```

---

### Task 14: Add opt-in bounded live smoke tests

**Objective:** Verify real guest-accessible contracts without making default CI dependent on Swiggy or private location data.

**Files:**
- Create: `tests/test_smoke.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `API_ENDPOINTS.md`
- Modify: `docs/findings.md`

**Step 1: Write skip-by-default tests**

Without `SWIGGY_LIVE=1`, the module skips. With live mode, require explicit `SWIGGY_LATITUDE` and `SWIGGY_LONGITUDE` or an approved saved location. Never embed a real coordinate.

**Step 2: Implement a bounded smoke**

The smoke test:

- requests one discovery page;
- limits results to three;
- enriches at most one venue;
- invokes only replay-allowlisted endpoint IDs;
- asserts stable ID, name, retrieval timestamp, and provenance;
- validates requested-location semantics;
- emits no raw payload;
- performs no mutations.

**Step 3: Run default mode**

Run: `uv run pytest tests/test_smoke.py -q`

Expected: skipped with a clear reason.

**Step 4: Run approved live mode**

Run locally with environment values supplied outside shell history where possible:

```bash
SWIGGY_LIVE=1 uv run pytest tests/test_smoke.py -q
```

Expected: pass or an exact documented provider blocker. A failure must update endpoint state/findings; never weaken assertions to obtain green.

**Step 5: Refresh evidence dates**

Update the endpoint ledger and findings with the live verification result, limitations, and date. Do not include coordinates or payloads.

**Step 6: Commit**

```bash
git add tests/test_smoke.py pyproject.toml README.md API_ENDPOINTS.md docs/findings.md
git commit -m "test: add opt-in live Dineout smoke checks"
```

---

### Task 15: Complete documentation and package-level acceptance gates

**Objective:** Verify every approved acceptance criterion and publish a release-ready repository state.

**Files:**
- Modify: `README.md`
- Modify: `API_ENDPOINTS.md`
- Modify: `docs/findings.md`
- Modify: `docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md`
- Create: `CHANGELOG.md`

**Step 1: Document actual behavior only**

README must cover installation, location approval, every CLI command, human/JSON examples generated from fixtures, guest/auth behavior, privacy, evidence labels, trend explanations, limitations, and opt-in live tests.

Mark the design status `Implemented` only after every required gate passes. Update endpoint states and findings from real evidence; remove resolved investigation questions.

**Step 2: Run the complete release candidate gate**

```bash
uv sync --all-groups --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pytest --cov=swiggy --cov-report=term-missing --cov-fail-under=90
uv run python scripts/validate_endpoint_ledger.py
uv run python scripts/check_public_tree.py
uv lock --check
uv build
uvx twine check dist/*
git diff --check
```

Expected: every command passes. Live smoke is separately required once with approved local location evidence but remains excluded from public CI.

**Step 3: Inspect package contents**

Install the wheel into a fresh temporary virtual environment and assert `EndpointRegistry.from_package_data()` loads the same endpoint IDs as `API_ENDPOINTS.md`. Verify wheel/sdist include package modules, generated endpoint registry, and required public docs but exclude `.hermes.md`, captures, sessions, raw payloads, APKs, caches, and private fixtures.

**Step 4: Reconcile the ten acceptance criteria**

Create a checklist in the final commit message/body or PR description mapping each design acceptance criterion to a test, command, or live evidence result. An unavailable required Swiggy field is acceptable only when represented honestly; inability to discover nearby venues is a release blocker.

**Step 5: Independent review**

Dispatch a read-only code reviewer against the complete diff and design. Resolve every P0-P2 finding and rerun the full gate. For public API, privacy, transport allowlisting, or mutation-safety findings, request the high-risk second opinion.

**Step 6: Commit and push**

```bash
git add README.md API_ENDPOINTS.md docs/findings.md docs/superpowers/specs/2026-09-06-swiggy-dineout-client-design.md CHANGELOG.md
git commit -m "docs: finalize swiggy-py version 1"
git push
```

Verify local `HEAD`, remote `main`, exact GitHub Actions `headSha`, workflow conclusion, and public repository contents before declaring version 1 complete.

---

## Requirement-to-task traceability

- Nearby discovery and pagination: Tasks 5, 8, 10, 14
- Details, offers, reviews, menus, facilities: Tasks 5, 9, 10
- Normalized JSON and field provenance: Tasks 2, 10, 12
- Guest-first optional authentication: Tasks 5, 6, 10, 13
- Approved location precedence/privacy: Task 7
- Deterministic ranking and trend evidence: Task 11
- Human and JSON CLI: Task 12
- Failure classification and graceful degradation: Tasks 6, 8, 9, 10
- Endpoint documentation/reconciliation: Tasks 3, 5, 14, 15
- Interesting findings maintenance: Tasks 4, 5, 11, 14, 15
- Security and no mutation: Tasks 3, 4, 6, 13, 14
- Fixture, contract, CLI, package, CI, live gates: Tasks 1–15
- Future District merger readiness: Tasks 2, 10, 12, 15

## Execution completion definition

The plan is complete only when:

1. all task commits exist and are pushed;
2. local and remote SHAs match;
3. the exact remote SHA has green CI;
4. the full local gate passes from a clean checkout;
5. one approved, bounded live smoke passes against current Swiggy behavior;
6. endpoint and findings documentation match that live evidence;
7. no raw private/authenticated material exists anywhere in the public Git history;
8. the implementation independently satisfies all ten design acceptance criteria.
