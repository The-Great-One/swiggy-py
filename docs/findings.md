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

## Open investigation questions

- Which current guest web contract powers nearby Dineout discovery?
- Which identifier links discovery cards to details, offers, reviews, and menu data?
- Are review timestamps and pagination exposed sufficiently for momentum scoring?
- Which nightlife/facility attributes are explicit versus presentation-only labels?
- Which Dineout fields require app authentication or device context?
- How does Swiggy represent legitimate empty results versus provider error cards?
