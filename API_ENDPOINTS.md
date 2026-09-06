# Swiggy Dineout Endpoint Reference

This is the canonical endpoint ledger for `swiggy-py`. It records only redacted, read-only evidence. Authentication values, cookies, OTPs, personal identifiers, exact private coordinates, and raw account payloads must never appear here.

## Evidence states

- **LIVE VERIFIED** — independently replayed and semantically successful.
- **CAPTURED** — observed from an official Swiggy client but not independently replayed.
- **STATIC ONLY** — recovered from current frontend/APK code and not invoked.
- **AUTH REQUIRED** — route exists but usable credentials are unavailable.
- **RETIRED/BROKEN** — route is obsolete, malformed, or no longer operational.

HTTP 200 alone is not semantic success. Error cards, empty fallback payloads, wrong-location responses, and login shells must be classified honestly.

## Endpoint matrix

No endpoints have been promoted yet. The design is approved; endpoint reconnaissance and semantic verification are the first implementation gate.

For each endpoint, record:

- method, host, and path;
- query/body/header inputs by name only;
- purpose and observed output fields;
- authentication and location requirements;
- pagination/cursor behavior;
- evidence state and verification date;
- redacted evidence source;
- limitations and parser notes.

## Coverage reconciliation

Implementation must maintain a machine-readable inventory of discovered routes and a test asserting that every in-scope route is represented here or explicitly excluded with a reason. Booking, reservation, payment, cart, cancellation, account mutation, and unrelated delivery endpoints are out of scope and must not be invoked.
