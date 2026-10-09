# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Managing subscriptions: `PolakoClient.list_subscriptions()` (one page of the subscriptions of your company, filtered by status, interval, text and creation time, sorted, with `limit` and `offset`; returns a `SubscriptionPage`), `get_subscription()` (a `SubscriptionDetails`: the customer, the card without its token, the charge history with the `payment_session_id` of every charge, and the event journal), and `pause_subscription()`, `resume_subscription()` and `cancel_subscription()`. They use the same `company_id` and `api_key` as `create_subscription`, work with the platform API key and are never retried. New public names: `SubscriptionPage`, `SubscriptionSummary`, `SubscriptionDetails`, `SubscriptionCustomer`, `SavedCard`, `ChargeAttempt`, `SubscriptionEvent`, `SubscriptionStatus`, `ChargeAttemptStatus`, `NotFoundError`. Documented in the README ("Managing a subscription") and shown in `examples/subscription_management_example.py`.- Documentation for subscriptions: the "Subscriptions" section of the README (creating a subscription, the card registration page, webhooks, the failed-registration notification, errors) and a complete merchant server in `examples/subscription_example.py`.
- `render_registration_form(form, *, auto_submit=True)`: turns the `registration_form` of a new subscription into a complete HTML page for your endpoint to return. A `FormPost` or `HppFormPost` becomes a form that posts itself to the card processor (with the field names the processor expects); a `RedirectForm` becomes a redirect page with a link. Values are HTML-escaped, the address must be an http or https URL, and the page loads nothing from elsewhere. With `auto_submit=False` the page needs no script and the customer presses a button.
- `parse_registration_failed(body, signature, api_key, *, allow_unsigned=False)`: checks and reads the notification the gateway POSTs to the `error_url` of a subscription when the card registration fails, and returns a `RegistrationFailed` (`subscription_id`, `merchant_subscription_ref`, `error_message`, `provider_name`, `signature_verified`). This body has no `event` field, so it is read with this function and not with `parse_subscription_webhook`; each rejects the other's bodies and says which function to use. A signature that is present is always checked; a notification without one is rejected unless `allow_unsigned=True`, which yields `signature_verified=False`.
- `parse_subscription_webhook(body, signature, api_key)`: checks the `X-Signature` of a subscription webhook over the raw request body and returns a typed event: `ChargeSucceeded`, `ChargeFailed`, `DroppedExternally`, `SubscriptionCancelled`, or `UnknownSubscriptionEvent` for a kind the SDK does not know. A wrong signature raises `WebhookSignatureError`, a missing one `MissingSignatureError`, a malformed body `WebhookPayloadError`. Pass the body exactly as received: JSON that was parsed and serialized again does not match the signature.
- `PolakoClient.create_subscription()`: creates a subscription and returns a `SubscriptionCreated` with the subscription ID, the 3DS registration form (`FormPost`, `HppFormPost` or `RedirectForm`) and the idempotency key that was used (generated when you do not pass one). The client takes `company_id` and `api_key` for it; the key is sent only with subscription calls. New public names: `BillingInterval`, `SubscriptionCreated`, `FormPost`, `HppFormPost`, `RedirectForm`, `ConfigurationError`, `UnknownRegistrationFormError`.
- Exception classes per HTTP status, all subclasses of `HttpRequestError`: `UnauthorizedError` (401), `ForbiddenError` (403), `ConflictError` (409), `RequestValidationError` (422), `RateLimitedError` (429, with `retry_after`) and `ServerError` (5xx). Existing `except HttpRequestError` code keeps working.
- The HTTP client retries a request that carries an `Idempotency-Key` on HTTP 429, 500, 502, 503 and 504 and on network errors a repeat can cure (timeouts, connection and protocol failures); 3 attempts, exponential backoff, `Retry-After` honoured, same key and body on every attempt. A status such as 501 or 505, an unsupported address or too many redirects are raised at once. Requests without that header, including all payment methods, are still sent once.

### Changed
- `create_subscription()` refuses an `amount` with more than two decimal places (`ValueError`): the gateway keeps cents and used to round the rest without a word. `990`, `990.5` and `990.00` are fine.
- A time that a webhook or a response carries without a timezone is read as UTC, so `ChargeSucceeded.charged_at` and the times of `SubscriptionDetails` are all timezone-aware. Offsets written `+02` or `+0200` and fractions of any length are read too (Python 3.10 could not read some of them).
- An HTTP 404 is now raised as `NotFoundError`. It is a subclass of `HttpRequestError`, so `except HttpRequestError` code keeps working; only code that tests the exact class of a 404 error is affected.
### Fixed
- The answer to a subscription request is checked as a whole: one without the subscription ID or the registration form, or with a malformed one, is an `HttpRequestError` at once, instead of a result with empty values that failed later.
- The page that `render_registration_form()` makes now submits the form through the form element's own method, so a field of the provider named `submit` or `action` no longer leaves the customer stuck on the "Continuing" page.
- The README (Quick Start and Custom Customer Address) and `examples/example.py` gave the customer's country as "Serbia", which the gateway rejects with HTTP 422: it takes a two-letter country code. They now use "RS", and the `CustomerAddress` documentation says so. The examples were checked against a running gateway.
- `create_order()` without an explicit `language` now always defaults to Serbian (`sr`). Previously the default was picked from an unordered set and could be `sr`, `en` or `ru` between interpreter runs.

## [0.1.9] - 2026-06-01

### Changed
- Version and README alignment for the 0.1.8 content.
- `_order.py` order-status surface extended.

## [0.1.8] - 2026-06-01

### Added
- `MerchantInfo` in the payment callback models.

### Changed
- **Breaking:** Python 3.9 support dropped, the package now requires Python >= 3.10.

### Security
- Patched 7 Dependabot alerts (h2, black, idna, pytest, filelock, virtualenv).

## [0.1.7] - 2026-05-23

### Added
- `check_order_status()` for querying the status of a payment session.
- `refund_session()` for full and partial refunds.
- Both methods use HMAC-SHA256 signature authentication.

## [0.1.6] - 2026-05-16

### Added
- Refunded items and amounts are exposed in `PaymentCallback`.

## [0.1.5] - 2026-05-15

### Added
- Support for the `generic_signed` callback format (schema 1.1) in `parse_payment_callback`.

## [0.1.4] - 2026-05-11

### Changed
- All endpoints now use the `/v1/` API prefix.
- SDK base URLs updated to the new `api.infra` hostnames.

## [0.1.3] - 2026-03-28

### Added
- `get_session_details()` for retrieving payment session info.

## [0.1.2] - 2026-03-22

### Added
- `get_payment_url()` for initiating payment on an existing session.

## [0.1.1] - 2025-11-02

### Added
- Initial public release: async client (httpx), HMAC-SHA256 signed `create_order`, payment callback parsing, PyPI publishing.

[Unreleased]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.9...HEAD
[0.1.9]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.8...release-v0.1.9
[0.1.8]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.7...release-v0.1.8
[0.1.7]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.6...release-v0.1.7
[0.1.6]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.5...release-v0.1.6
[0.1.5]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.4...release-v0.1.5
[0.1.4]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.3...release-v0.1.4
[0.1.3]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.2...release-v0.1.3
[0.1.2]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.1...release-v0.1.2
[0.1.1]: https://github.com/Polako-Finance/python-sdk/releases/tag/release-v0.1.1
