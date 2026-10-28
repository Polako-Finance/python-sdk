# python-sdk — Status

> **Platform tracking**: [Migration Status](../../documentation/target-state/migration-status.md)

## Current State

Active. Minimal migration impact.

## Branches

| Branch | Purpose | Status |
|--------|---------|--------|
| `main` | Production | Stable (tag: `release-v0.2.2`) |
| `develop` | Development | Active |

## Releases

- **v0.1.4** — Added `/v1/` API prefix to all endpoints (gateway path migration)
- **v0.1.5** — `generic_signed` schema 1.1 update
- **v0.1.6** (2026-05-19) — Expose refunded items + amounts in PaymentCallback
- **v0.1.7** (2026-05-26) — `check_order_status()` for querying payment status + `refund_session()` for full/partial refunds; both use HMAC-SHA256 signature authentication
- **v0.1.8** (2026-06-01) — `MerchantInfo` added to callback models; Python 3.9 support dropped (now requires >= 3.10); 7 Dependabot alerts patched (h2, black, idna, pytest, filelock, virtualenv)
- **v0.1.9** (2026-06-01) — version/README alignment for the 0.1.8 content; `_order.py` order-status surface extended
- **v0.2.0** (2026-10-12) — subscriptions: create and manage (`create_subscription`, list/get/pause/resume/cancel), `render_registration_form`, subscription webhook and `RegistrationFailed` parsers; retries for requests with an `Idempotency-Key`; per-status HTTP exception classes
- **v0.2.1** (2026-10-21) — network failures and the errors of the transport are an `HttpClientError` with a message that names the failure (those that were an `HttpRequestError` before, for errors `httpx` does not wrap, are no longer one); new `InvalidArgumentError` and `InvalidHeaderValueError` (both `ValueError`s); a failure of closing the connection is logged, not raised, also at the exit of `async with`; retries of TLS and transport failures are told apart; dependency `anyio >= 3`, `httpx < 1.0`
- **v0.2.2** (2026-10-27) — an order may be in any of the four currencies the gateway takes on a session (`RSD`, `RUB`, `EUR`, `USD`); the SDK allowed `RSD` alone, so a rouble or euro order was refused by `OrderDetails.validate()` before any request. An order without a currency is still sent in `RSD` (`DEFAULT_CURRENCY`). Found by polako-hedonist's rouble-card button, which pins this SDK (PR #6)
