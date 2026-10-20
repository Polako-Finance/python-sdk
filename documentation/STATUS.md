# python-sdk — Status

> **Platform tracking**: [Migration Status](../../documentation/target-state/migration-status.md)

## Current State

Active. Minimal migration impact.

## Branches

| Branch | Purpose | Status |
|--------|---------|--------|
| `main` | Production | Stable (tag: `release-v0.2.1`) |
| `develop` | Development | Active |

## Releases

- **v0.1.4** — Added `/v1/` API prefix to all endpoints (gateway path migration)
- **v0.1.5** — `generic_signed` schema 1.1 update
- **v0.1.6** (2026-05-19) — Expose refunded items + amounts in PaymentCallback
- **v0.1.7** (2026-05-26) — `check_order_status()` for querying payment status + `refund_session()` for full/partial refunds; both use HMAC-SHA256 signature authentication
- **v0.1.8** (2026-06-01) — `MerchantInfo` added to callback models; Python 3.9 support dropped (now requires >= 3.10); 7 Dependabot alerts patched (h2, black, idna, pytest, filelock, virtualenv)
- **v0.1.9** (2026-06-01) — version/README alignment for the 0.1.8 content; `_order.py` order-status surface extended
- **v0.2.0** (2026-10-12) — subscriptions: create and manage (`create_subscription`, list/get/pause/resume/cancel), `render_registration_form`, subscription webhook and `RegistrationFailed` parsers; retries for requests with an `Idempotency-Key`; per-status HTTP exception classes
- **v0.2.1** (2026-10-20) — the message of `HttpClientError` for a network failure names the failure
