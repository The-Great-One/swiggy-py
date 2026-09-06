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

## Open investigation questions

- Which current guest web contract powers nearby Dineout discovery?
- Which identifier links discovery cards to details, offers, reviews, and menu data?
- Are review timestamps and pagination exposed sufficiently for momentum scoring?
- Which nightlife/facility attributes are explicit versus presentation-only labels?
- Which Dineout fields require app authentication or device context?
- How does Swiggy represent legitimate empty results versus provider error cards?
