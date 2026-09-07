# Swiggy Dineout Findings

This document records current, reusable discoveries and limitations while building `swiggy-py`. It is not a raw transcript or a dump of private payloads.

## Documentation rules

Each finding should include:

- date and evidence source;
- concise observation;
- confidence/evidence state;
- implication for the client;
- relevant endpoint ledger entry or source path;
- discarded hypothesis when it prevents repeated work.

Never include credentials, cookies, OTPs, phone numbers, account identifiers, exact private coordinates, unredacted headers, or private payloads.

## Current findings

### 2026-09-06 — Project baseline

- **Observation:** The client will be developed independently from `zomato-py`, then integrated later through a provider-neutral merger.
- **Confidence:** User-approved design decision.
- **Implication:** Swiggy-specific transport and parsing remain isolated; normalized records intentionally resemble the District client’s venue concepts without importing it.

### 2026-09-06 — Guest-first hybrid strategy

- **Observation:** Broad discovery should prefer guest-accessible web contracts; app/Dineout contracts are candidates only for fields missing from web and require read-only live verification before promotion.
- **Confidence:** User-approved architecture; endpoint-level feasibility still unverified.
- **Implication:** Authentication cannot be a prerequisite for baseline nearby discovery, and missing enrichment must degrade gracefully.

### 2026-09-06 — Written design approved

- **Observation:** The complete written design was approved for implementation planning.
- **Confidence:** Explicit user approval.
- **Implication:** Execution may proceed from the canonical implementation plan, with endpoint reconnaissance remaining the first network-dependent gate.

### 2026-09-06 — Guest page contains server-rendered Dineout cards

- **Observation:** The official `/dineout` page loaded without login. Its Next.js `pageProps.widgetResponse.success` contained `cards`, `pageOffset`, `firstOffsetRequest`, and `nextFetch`. Card types included a filter/sort widget and a restaurant grid.
- **Confidence:** CAPTURED browser evidence only; independent HTTP replay and requested-location validation are pending.
- **Implication:** Server-rendered page data is a potential guest discovery source, but the observed default page showed Delhi, not an approved Gurugram query. Do not claim nearby Gurugram support from this observation.
- **Privacy:** The surrounding widget envelope contains session/device identifiers and encoded location context; retain only allowlisted restaurant fields in public fixtures.

### 2026-09-07 — Capture sanitization boundary

- **Observation:** Reconnaissance utilities retain only method, host, path, scope, and evidence state from HAR-like input; headers, query/body values, response bodies, and device/session fields are discarded rather than copied.
- **Confidence:** Fixture-tested implementation.
- **Implication:** Raw browser captures stay outside Git. Derived route inventory is safe to reconcile against `API_ENDPOINTS.md`, but it is not proof that a route is replayable or semantically successful.
- **Discarded approach:** Retaining redacted response payloads was rejected because even partially sanitized authenticated payloads can preserve unnecessary personal or session data.

### 2026-09-07 — Guest web contracts replayed successfully

- **Observation:** A same-origin guest `GET /dineout` returned HTTP 200 HTML with Next data, restaurant cards, restaurant links, a non-empty next offset indicator, and offer text. A same-origin guest detail GET redirected to the canonical restaurant route and returned HTTP 200 HTML with restaurant ID, rating, offers, menu section/page counts, hours, cuisines, and seven amenities.
- **Confidence:** `LIVE VERIFIED` for the two web contracts in `API_ENDPOINTS.md`; replay assertions checked semantic fields, not status alone.
- **Implication:** Version 1 can implement guest HTML/Next-data discovery and detail parsing without login. Reviews were not present in the captured detail payload, so reviews remain an open enrichment contract.
- **Limitation:** The browser’s provider-selected default was Delhi. Gurugram-specific location routing has not yet been replayed and must not be inferred from this result.
- **Excluded traffic:** `/dapi/cart` and analytics/telemetry requests were observed but are outside the read-only Dineout contract and are not replayable.

### 2026-09-07 — Explainable ranking evidence boundary

- **Observation:** Ranking keeps quality, momentum, freshness, offer strength, confidence, and distance as separate components. Quality uses a documented Bayesian prior and log-scaled rating volume; momentum requires dated recent and older review windows; expired offers score zero; nightlife/freshness require explicit provider-declared signals.
- **Confidence:** Formula-tested deterministic implementation; provider evidence coverage varies by field.
- **Implication:** High rating alone does not qualify a venue as trending. Missing timestamps or freshness markers produce `insufficient evidence` rather than inferred trends. Distance is reported separately and does not silently alter quality.
- **Limitation:** The current normalized model has no dedicated new/listed/campaign timestamp field, so freshness remains unavailable unless an explicit provider attribute is present.

## Open investigation questions

- Which current guest web contract powers nearby Dineout discovery?
- Which identifier links discovery cards to details, offers, reviews, and menu data?
- Are review timestamps and pagination exposed sufficiently for momentum scoring?
- Which nightlife/facility attributes are explicit versus presentation-only labels?
- Which Dineout fields require app authentication or device context?
- How does Swiggy represent legitimate empty results versus provider error cards?
