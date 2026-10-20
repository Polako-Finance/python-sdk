# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-10-20

### Added
- `InvalidArgumentError` (a `ValueError`): the class of every argument check of the SDK (an order, a customer, a refund, a subscription, a list query, an ID), raised before anything is sent. Code that catches `ValueError` keeps working; code that needs to tell an invalid argument from another `ValueError` can catch this class.
- `InvalidHeaderValueError` (an `InvalidArgumentError`): a value that would be sent as a header and cannot be, because it is not printable ASCII (a tab inside is fine), is of a type that cannot be sent, or has whitespace at either end. `create_subscription()` raises it for an `idempotency_key` that is blank, is neither a string nor a `UUID`, or cannot be sent, and the HTTP client for any header value; a header name that is not an ASCII token is an `InvalidArgumentError`; the message names the argument or header, never the value.

### Changed
- A failure of closing the HTTP client by a call (outside `async with`, or the last user of a shared client) no longer replaces the outcome of the call: it is logged at warning level with its traceback (`polako.sdk._async_client`), also at the exit of `async with`, where the error that is propagating is no longer replaced. The close is bounded to 10 seconds (`CLOSE_TIMEOUT`), so a call can take that long to return if the server does not answer the close. A call that is cancelled while it closes leaves at once and the close finishes in the background.
- A stream that `anyio` reports as cut (`EndOfStream`, `BrokenResourceError`) and that `httpcore` does not map used to come out as an `HttpRequestError` (`Unexpected error during request`) and was not retried; it is now an `HttpClientError` and is retried for a request with an `Idempotency-Key`.
- A TLS error with the reason `UNEXPECTED_EOF_WHILE_READING` (a cut connection) is retried. The handshake alerts `SSLV3_ALERT_UNEXPECTED_MESSAGE` and `TLSV1_ALERT_DECODE_ERROR` are not (under TLS 1.3 they are deterministic rejections).
- `REFUND_REASON_MIN_LENGTH` and `REFUND_REASON_MAX_LENGTH` (3 and 255, the limits of the reason of a refund) are exported from `polako.sdk`.
- `anyio >= 3` is declared as a dependency: the SDK imports its error classes (it came with `httpx` before).
- Leaving `async with` more often than entering it (calling `__aexit__` by hand twice, or on a client that was never entered) does nothing but emit a `RuntimeWarning`; it will be a `RuntimeError` from 0.3.0. The warning points at your code; while an error is propagating it goes to the log instead. Entering the same client again (nested, or from another task) shares one client, and the client is closed when the last context has exited and no call is still using it, so a call made outside `async with` while another task holds it can be the one that closes it.
- The dependency is now `httpx >= 0.25, < 1.0` (it had no upper bound); the tests run on the newest `httpx` of the lock file and, in a separate CI job, on 0.25.0, the floor.
- The message of an `HttpClientError` raised before an answer arrived now starts with `Request failed:` instead of `Network error during request:`, because not every such failure is a network one (a request that could not be built, an answer that could not be decoded). It names the failure: a timeout or a reset connection comes from `httpx` with an empty text, so the message used to end after the colon; it is now, for example, `Request failed: ReadTimeout`. An error that has a text keeps it after the class name (`Request failed: ConnectError: All connection attempts failed`); with no text, the reason found deeper on the error chain is used. After more than one attempt the message, of a failure or of an error answer, says how many were made. The original error is still `__cause__`.
- An error answer with an empty body (typical for a proxy or a load balancer) no longer gives a message that ends after the colon: `HTTP request failed with status 502`.
- `create_subscription()` and the other subscription calls raise `ConfigurationError` for an `api_key` that is not a string (bytes included) or cannot be sent as a header (typically a trailing newline from a file); the message says which of the two and never holds the key.
- The message of an unexpected failure (`HttpRequestError`, `Unexpected error during request: ...`) now includes the class of the error (`TypeError: ...`) and no longer ends after the colon when the error has no text. The text of the innermost `OSError` on the chain is used only for the errors of `httpx`, never for an unrelated error.

### Fixed
- The API key could appear in the text and `__cause__` of the exception when it had whitespace at the end; it is now refused before anything is sent.
- A non-ASCII `idempotency_key` gave an `HttpRequestError` with no status; it is now an `InvalidHeaderValueError`.
- A failure that `httpx` does not wrap was reported as an answer of the gateway (`HttpRequestError`) and never retried; it is now an `HttpClientError`. For a request with an `Idempotency-Key` it is retried when a repeat can cure it: a connection that was reset, aborted, refused or broken, a timeout of the system, a TLS connection that was cut, or, on an established connection, a record that was damaged (any other TLS failure, and any failure of the handshake except a cut connection, is raised at once). Not retried, because a repeat gives the same result: a certificate that does not verify (also when it is a failure to connect), a wrong TLS protocol version (told apart by the `reason` code of the error, not by its text), a failure to set up the client, such as a certificate file that exists but is malformed or a proxy setting that cannot be used (an `HttpClientError` `Client set-up failed: ...`, raised at `async with`, or at the call when `async with` is not used). An error the caller is handling when the call runs is not taken for the reason of the failure.
- `create_subscription()` accepts a `UUID` as `idempotency_key`, as its documentation recommends; it used to fail with an `AttributeError`.
- The message of an unexpected failure no longer ends after the colon when the error has no text.

## [0.2.0] - 2026-10-12

### Added
- Managing subscriptions: `PolakoClient.list_subscriptions()` (one page of the subscriptions of your company, filtered by status, interval, text and creation time, sorted, with `limit` and `offset`; returns a `SubscriptionPage`), `get_subscription()` (a `SubscriptionDetails`: the customer, the card without its token, the charge history with the `payment_session_id` of every charge, and the event journal), and `pause_subscription()`, `resume_subscription()` and `cancel_subscription()`. They use the same `company_id` and `api_key` as `create_subscription`, work with the platform API key and are never retried. New public names: `SubscriptionPage`, `SubscriptionSummary`, `SubscriptionDetails`, `SubscriptionCustomer`, `SavedCard`, `ChargeAttempt`, `SubscriptionEvent`, `SubscriptionStatus`, `ChargeAttemptStatus`, `NotFoundError`. Documented in the README ("Managing a subscription") and shown in `examples/subscription_management_example.py`.
- Documentation for subscriptions: the "Subscriptions" section of the README (creating a subscription, the card registration page, webhooks, the failed-registration notification, errors) and a complete merchant server in `examples/subscription_example.py`.
- `render_registration_form(form, *, auto_submit=True)`: turns the `registration_form` of a new subscription into a complete HTML page for your endpoint to return. A `FormPost` or `HppFormPost` becomes a form that posts itself to the card processor (with the field names the processor expects); a `RedirectForm` becomes a redirect page with a link. Values are HTML-escaped, the address must be an http or https URL, and the page loads nothing from elsewhere. The page always shows a "Continue" button too, for a browser or a page policy that blocks the script. With `auto_submit=False` the page holds no script and the customer presses the button.
- `parse_registration_failed(body, signature, api_key, *, allow_unsigned=False)`: checks and reads the notification the gateway POSTs to the `error_url` of a subscription when the card registration fails, and returns a `RegistrationFailed` (`subscription_id`, `merchant_subscription_ref`, `error_message`, `provider_name`, `signature_verified`). This body has no `event` field, so it is read with this function and not with `parse_subscription_webhook`; each rejects the other's bodies and says which function to use. A signature that is present is always checked; a notification without one is rejected unless `allow_unsigned=True`, which yields `signature_verified=False`.
- `parse_subscription_webhook(body, signature, api_key)`: checks the `X-Signature` of a subscription webhook over the raw request body and returns a typed event: `ChargeSucceeded`, `ChargeFailed`, `DroppedExternally`, `SubscriptionCancelled`, or `UnknownSubscriptionEvent` for a kind the SDK does not know. A wrong signature raises `WebhookSignatureError`, a missing one `MissingSignatureError`, a malformed body `WebhookPayloadError`. Pass the body exactly as received: JSON that was parsed and serialized again does not match the signature. Times in events (and in the results of the management methods) are always timezone-aware: a time the server sends without a zone is read as UTC, the seconds may be left out, and a date with no time of day is refused.
- `PolakoClient.create_subscription()`: creates a subscription and returns a `SubscriptionCreated` with the subscription ID, the 3DS registration form (`FormPost`, `HppFormPost` or `RedirectForm`) and the idempotency key that was used (generated when you do not pass one). The client takes `company_id` and `api_key` for it; the key is sent only with subscription calls. `amount` may have at most two decimal places (`ValueError` otherwise, asking you to round to cents first): the gateway keeps cents and would round the rest without a word. `990`, `990.5` and `990.00` are fine. New public names: `BillingInterval`, `SubscriptionCreated`, `FormPost`, `HppFormPost`, `RedirectForm`, `ConfigurationError`, `UnknownRegistrationFormError`.
- Exception classes per HTTP status, all subclasses of `HttpRequestError`: `UnauthorizedError` (401), `ForbiddenError` (403), `ConflictError` (409), `RequestValidationError` (422), `RateLimitedError` (429, with `retry_after`) and `ServerError` (5xx). Existing `except HttpRequestError` code keeps working.
- The HTTP client retries a request that carries an `Idempotency-Key` on HTTP 429, 500, 502, 503 and 504 and on network errors a repeat can cure (timeouts, connection and protocol failures); 3 attempts, exponential backoff, `Retry-After` honoured, same key and body on every attempt. A read timeout is repeated too (safe because the server replays a key it knows), every attempt counts against the endpoint's limit of 20 requests per 60 seconds, and there is no overall deadline: a minute and a half or more at worst, because the 30 second timeout applies to each phase of an attempt. A status such as 501 or 505, an unsupported address or too many redirects are raised at once. Requests without that header, including all payment methods, are still sent once.

### Changed
- **Behaviour change that may break your code:** `PaymentCallback.datetime` of a schema 1.1 payment callback is now always timezone-aware. A `timestamp` without a zone is read as UTC (it used to give a naive value), and offsets written `+02` or `+0200` and fractions of any length are read too (Python 3.10 could not read some of them). Code that compares it with a naive `datetime.utcnow()` now gets a `TypeError`; compare with `datetime.now(timezone.utc)`. The legacy callback format carries only the minute and no zone, so its `datetime` stays naive: if you accept both formats, handle the two kinds apart.
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

[Unreleased]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.2.1...HEAD
[0.2.1]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.2.0...release-v0.2.1
[0.2.0]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.9...release-v0.2.0
[0.1.9]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.8...release-v0.1.9
[0.1.8]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.7...release-v0.1.8
[0.1.7]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.6...release-v0.1.7
[0.1.6]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.5...release-v0.1.6
[0.1.5]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.4...release-v0.1.5
[0.1.4]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.3...release-v0.1.4
[0.1.3]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.2...release-v0.1.3
[0.1.2]: https://github.com/Polako-Finance/python-sdk/compare/release-v0.1.1...release-v0.1.2
[0.1.1]: https://github.com/Polako-Finance/python-sdk/releases/tag/release-v0.1.1
