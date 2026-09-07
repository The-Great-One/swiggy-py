# Swiggy Dineout Endpoint Reference

This Markdown file is the sole human-edited authority for endpoint metadata in `swiggy-py`. The generated package registry must be produced from it; production Python modules must not contain handwritten endpoint hosts, paths, or URLs.

Only redacted, read-only evidence belongs here. Authentication values, cookies, OTPs, personal identifiers, exact private coordinates, and raw account payloads must never appear.

## Evidence states

- **LIVE VERIFIED** — independently replayed and semantically successful.
- **CAPTURED** — observed from an official Swiggy client but not independently replayed.
- **STATIC ONLY** — recovered from current frontend/APK code and not invoked.
- **AUTH REQUIRED** — route exists but usable credentials are unavailable.
- **RETIRED/BROKEN** — route is obsolete, malformed, or no longer operational.

HTTP 200 alone is not semantic success. Error cards, empty fallback payloads, wrong-location responses, and login shells must be classified honestly. No route may enter the runtime registry unless it is a read-only `GET`, is `LIVE VERIFIED`, and has `safe_to_replay` set to `true`.

## Endpoint record schema

Every documented endpoint gets its own subsection containing exactly one fenced `endpoint-json` object. Ordinary JSON fences are documentation only and are not parsed. All fields shown below are required.

```json
{
  "id": "stable-kebab-id",
  "method": "GET",
  "host": "example.invalid",
  "path": "/redacted/template/{id}",
  "state": "STATIC ONLY",
  "auth": "guest",
  "location": "none",
  "pagination": "unknown",
  "purpose": "Short semantic description",
  "allowed_inputs": ["named-input-only"],
  "observed_fields": ["semantic-field"],
  "limitations": ["Known limitation"],
  "evidence_source": "static: redacted source reference",
  "semantic_evidence": "",
  "last_verified": null,
  "in_scope": true,
  "safe_to_replay": false
}
```

Allowed enumerations:

- `method`: `GET` only;
- `state`: `LIVE VERIFIED`, `CAPTURED`, `STATIC ONLY`, `AUTH REQUIRED`, or `RETIRED/BROKEN`;
- `auth`: `guest`, `optional`, or `required`;
- `location`: `none`, `query`, `headers`, or `body`;
- `pagination`: `none`, `offset`, `cursor`, or `unknown`.

A `LIVE VERIFIED` record additionally requires an ISO 8601 date in `last_verified`, non-empty `semantic_evidence`, a redacted replay evidence source, and a semantic success check stronger than HTTP status.

## Endpoint records

### dineout-discovery

```endpoint-json
{
  "id": "dineout-discovery",
  "method": "GET",
  "host": "www.swiggy.com",
  "path": "/dineout",
  "state": "LIVE VERIFIED",
  "auth": "guest",
  "location": "none",
  "pagination": "cursor",
  "purpose": "Guest Dineout discovery page with server-rendered restaurant cards",
  "allowed_inputs": [],
  "observed_fields": ["cards", "next_offset", "restaurant_links", "offer_text"],
  "limitations": ["Default page location is provider-selected; requested Gurugram location still needs explicit browser location validation"],
  "evidence_source": "replay: browser same-origin GET with redacted semantic assertions",
  "semantic_evidence": "Response returned cards, next_offset, restaurant_links, and offer_text in guest HTML and Next data",
  "last_verified": "2026-09-07",
  "in_scope": true,
  "safe_to_replay": true
}
```

### dineout-restaurant-detail

```endpoint-json
{
  "id": "dineout-restaurant-detail",
  "method": "GET",
  "host": "www.swiggy.com",
  "path": "/restaurants/{city}/{area}/{name}/dineout",
  "state": "LIVE VERIFIED",
  "auth": "guest",
  "location": "none",
  "pagination": "none",
  "purpose": "Guest Dineout restaurant detail page",
  "allowed_inputs": ["city", "area", "name"],
  "observed_fields": ["restaurant_id", "offers", "menu", "amenities", "hours", "rating"],
  "limitations": ["Canonical redirects may normalize the supplied slug; reviews were not present in the captured detail payload"],
  "evidence_source": "replay: browser same-origin GET with redacted semantic assertions",
  "semantic_evidence": "Response returned restaurant_id, offers, menu, amenities, hours, and rating in guest HTML and Next data",
  "last_verified": "2026-09-07",
  "in_scope": true,
  "safe_to_replay": true
}
```

## Coverage reconciliation

`tests/fixtures/route_inventory.json` is the redacted discovered-route inventory. Every in-scope inventory route must match one ledger record by `(method, host, path)`. Every excluded route must carry an explicit reason. The validator reports missing, excluded, and undocumented sets and fails when in-scope coverage differs.

Booking, reservation, payment, cart, cancellation, account mutation, and unrelated delivery routes are outside scope and must not be invoked or represented as replayable endpoints.
