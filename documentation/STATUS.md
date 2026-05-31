# python-sdk — Status

> **Platform tracking**: [Migration Status](../../documentation/target-state/migration-status.md)

## Current State

Active. Minimal migration impact.

## Branches

| Branch | Purpose | Status |
|--------|---------|--------|
| `main` | Production | Stable (tag: `release-v0.1.7`) |
| `develop` | Development | Active |

## Releases

- **v0.1.4** — Added `/v1/` API prefix to all endpoints (gateway path migration)
- **v0.1.5** — `generic_signed` schema 1.1 update
- **v0.1.6** (2026-05-19) — Expose refunded items + amounts in PaymentCallback
- **v0.1.7** (2026-05-26) — `check_order_status()` for querying payment status + `refund_session()` for full/partial refunds; both use HMAC-SHA256 signature authentication
