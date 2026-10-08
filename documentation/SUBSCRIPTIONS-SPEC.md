# python-sdk — Subscriptions: client-facing specification

**Status: DRAFT v0.11** — agreed in principle on 2026-10-08. Implemented so far: exceptions by status, the retry
gate, wire aliases, the models, `create_subscription`, the webhook signature check, `parse_subscription_webhook` and
`parse_registration_failed` and `render_registration_form`, plus the README section and the example. Scope: **creating a subscription, full cycle**
(create, render the 3DS form, receive webhooks). Subscription management comes later, after the gateway accepts the platform API key
for it (see Planned).

## How to use this document

This is the source of truth for the subscription surface of the SDK. The order of work is outside-in:

1. the interface and the merchant example (`examples/subscription_example.py`) are agreed first;
2. tests and implementation follow them; if the implementation cannot match, the **spec is changed first** (see the
   change log), then the code;
3. `examples/` and the README sections are written from it and must match it (the docs checker verifies signatures).

Any deviation from this file is a spec change: edit the file, add a change-log row, then change the code.

## Scope

In: authentication of the create call, `create_subscription`, models for the request, the response and the three
registration forms, form rendering helper, webhook parsers (four lifecycle events and the registration-failed
notification), exceptions by HTTP status, retries for keyed requests.

Out: management methods (detail, list, pause, resume, cancel, payments; blocked on the gateway, see Planned), retries for payment methods,
unification of the two signature schemes, `SubscriptionStatus` / `ChargeAttemptStatus` enums, live checks on production,
a public `verify_webhook_signature` (see Decisions).

## Gateway contract (verified 2026-10-08)

- `POST /v1/company/{company_id}/subscriptions`, status 201. Headers: `company_api_key` (the API key of the platform, the
  same value that signs payment requests) and a mandatory `Idempotency-Key`. A repeat with the same key returns the
  original response.
- Body (the server accepts camelCase and snake_case, responses are camelCase only): `customerEmail`, `amount` (> 0),
  `currency`, `billingInterval` (`daily` `weekly` `monthly` `quarterly` `yearly`), `merchantSubscriptionRef` (1-128 chars),
  `successUrl`, `cancelUrl`, `errorUrl` (http or https).
- Response: `subscriptionId` and `registrationForm`, a union discriminated by `type`:
  `form_post` (`action`, `version`, `merchantId`, `terminalId`, `totalAmount`, `currency`, `locale`, `purchaseTime`,
  `orderId`, `signature`), `hpp_form_post` (`action`, `fields`: dict of strings), `iframe` (`action`).
  Despite its name, `iframe` carries only a redirect address (that is all a hosted-payment provider returns): it is a
  redirect target, not an embeddable page.
- Errors: 401 (missing or unknown key), 403 (key belongs to another company), 409 (subscriptions disabled for the company,
  or the customer already has a live subscription for the same `merchantSubscriptionRef`), 422 (invalid fields or key, and
  a currency outside the platform-wide allow-list the platform operator configures), 502 (the provider
  rejected the card registration request).
- Lifecycle webhooks go to `credentials["callback_url"]` of the platform (set in the platform settings in the
  dashboard, field `callback_url`: optional for generic platforms, required for one platform type): signed with HMAC-SHA256 over the raw compact
  JSON body with sorted keys, hex digest in `X-Signature`, key = the platform API key. Three attempts (1 s, 2 s back-off)
  on 5xx or network errors, 4xx is final.
  - `charge_succeeded`: `event`, `subscription_id`, `merchant_subscription_ref`, `amount` (string), `currency`, `charged_at` (ISO)
  - `charge_failed`: `event`, `subscription_id`, `merchant_subscription_ref`, `error_class`
  - `dropped_externally`, `cancelled`: `event`, `subscription_id`, `merchant_subscription_ref`
- Registration failure goes to the `errorUrl` of the subscription: no `event` field; `order_id` (always equal to
  `subscription_id`), `subscription_id`, `merchant_subscription_ref`, `success` (always 0), `error_message`,
  `provider_name`; one attempt, 10 s timeout, no retries.
  Signed with the same scheme when the subscription is linked to a platform (always true for subscriptions created with a
  platform API key), otherwise sent without `X-Signature`.
- Cancelling is console-only (JWT), so the end-to-end example ends at receiving the `cancelled` webhook.

## Target merchant code (acceptance example)

The acceptance example is `examples/subscription_example.py`, a complete merchant server (create a subscription, return the
card registration page, read the webhooks and the registration-failure notification, with the SDK's errors turned into HTTP
answers). The `Subscriptions` section of the README shows the same flow in pieces. Both are verified against the real
signatures by the documentation check, and the example has been run end to end against the gateway emulator of the
tests. A change to the flow is made in this spec first, then in the example and the README.

## Interface

| Item | Signature |
|------|-----------|
| Client | `PolakoClient(timeout=30.0, test_env=False, company_id: UUID \| None = None, api_key: str \| None = None)`; payment methods unchanged |
| Create | `await create_subscription(*, customer_email, amount: Decimal, currency: str, billing_interval: BillingInterval, merchant_subscription_ref, success_url, cancel_url, error_url, idempotency_key: str \| None = None) -> SubscriptionCreated` |
| Result | `SubscriptionCreated`: `subscription_id`, `registration_form`, `idempotency_key` (the one used, also when generated) |
| Form | `registration_form` is `FormPost`, `HppFormPost` or `RedirectForm` (wire `type` is `iframe`); `render_registration_form(form, *, auto_submit=True) -> str` returns a complete HTML page for the merchant to return as an HTML response |
| Events | `parse_subscription_webhook(body: bytes \| str, signature: str \| None, api_key: str)` returns `ChargeSucceeded` (`amount`, `currency`, `charged_at`), `ChargeFailed` (`error_class`), `DroppedExternally`, `SubscriptionCancelled` or `UnknownSubscriptionEvent` (`event`, `data`); all carry `subscription_id` (a `UUID`) and `merchant_subscription_ref` (may be `None`), are immutable, and are covered by the `SubscriptionWebhookEvent` type alias |
| Registration failure | `parse_registration_failed(body, signature: str \| None, api_key, *, allow_unsigned=False) -> RegistrationFailed`: `subscription_id` (a `UUID`), `merchant_subscription_ref`, `error_message`, `provider_name` (each may be `None` but the id), `signature_verified`; immutable. The model states that it has no event (`event = None`, unlike every lifecycle event) and that `success = 0`; `order_id` is not kept because it always equals `subscription_id` |
| Exceptions | `UnauthorizedError` (401), `ForbiddenError` (403), `ConflictError` (409), `RequestValidationError` (422), `RateLimitedError` (429, `retry_after`), `ServerError` (5xx), all subclasses of `HttpRequestError`; `ConfigurationError` (missing `company_id` or `api_key`, a `ValueError`); `UnknownRegistrationFormError` (a `ValueError`; surfaces as the `__cause__` of the `HttpRequestError` the client raises when it cannot read the response); `WebhookSignatureError`, `MissingSignatureError` (a `WebhookSignatureError`), `WebhookPayloadError` (a `ValueError`: the signed body is not JSON, not an object, has no event name, or a field is missing or malformed) |

Behaviour rules:
- `create_subscription` without `company_id` or `api_key` raises a clear configuration error before any request.
- The `company_api_key` header is set only on subscription calls; signed payment calls are unchanged.
- The API key never appears in logs, `repr` or exception text.
- Webhook signatures are verified over the raw body exactly as received, with `hmac.compare_digest`; a forged signature raises
  `WebhookSignatureError` (never `AssertionError`).
- Arguments are checked before any request and raise `ValueError`: `customer_email` contains `@` and no spaces; `amount` is a
  finite `Decimal` greater than zero (floats are rejected); `currency` is not empty; `billing_interval` is a
  `BillingInterval` or its string value; `merchant_subscription_ref` is 1 to 128 characters; the three URLs are http or
  https with a host; a given `idempotency_key` is not blank. Everything else is left to the server.
- `amount` is sent as a plain decimal string (`990.00`, `1000` for `Decimal("1E+3")`), never with an exponent.
- `SubscriptionCreated` is immutable. The client keeps the API key private and hides it in `repr`.
- A webhook is verified before it is read: the signature is checked over the raw body exactly as received, and only then
  is the body decoded (UTF-8 JSON only, a JSON object). A forged body is a `WebhookSignatureError` whatever it contains,
  never a `WebhookPayloadError`. A body that was parsed and serialized again does not match; the docs say so.
- The registration-failure notification and the lifecycle events are told apart explicitly, in both directions. A body
  with an `event` field is not a registration failure: `parse_registration_failed` rejects it and points to
  `parse_subscription_webhook`. A body with `success` and no `event` is not a lifecycle event: the lifecycle parser rejects
  it and points to `parse_registration_failed`. In a registration failure `success` must be `0` or `false` (a missing or
  `null` one is accepted); anything else is rejected as not being a failure.
- A signature that is present on a registration failure is always checked, whatever `allow_unsigned` says; a wrong one is
  never accepted. A missing (or blank) signature is rejected unless `allow_unsigned=True`, and then the result has
  `signature_verified=False` and is otherwise read and validated exactly like a signed one. `allow_unsigned` is
  keyword-only, and an empty `api_key` is a `ConfigurationError` in every mode.
- The rendered page follows the card processor's expectations, not the gateway's naming. A `FormPost` becomes a POST form
  with nine hidden inputs named `Version`, `MerchantID`, `TerminalID`, `TotalAmount`, `Currency`, `Locale`, `PurchaseTime`,
  `OrderID` and `Signature` (an empty version is sent as `1`); an `HppFormPost` passes the provider's fields through as
  given, in order; a `RedirectForm` is a link, plus a `refresh` redirect when `auto_submit` is on, never a form and never
  an `<iframe>`. With `auto_submit` on a posted form submits itself with one constant script and has a button inside
  `<noscript>`; with it off the page has a visible button and no script (for sites that forbid inline scripts).
- The helper refuses what could be turned against the customer: the address must be an http or https URL with a host, and
  must contain no whitespace or control characters (`ValueError`); every name, value and address is HTML-escaped; the
  script holds no data from the form; the page loads nothing from elsewhere; anything that is not a registration form is a
  `TypeError`. The input names for `FormPost` are taken from the working reference page of the gateway's own integration
  tools; confirm them against the staging environment before relying on them in production.
- Times with a trailing `Z` are read as UTC on every supported Python version. An unknown event name is returned, not
  raised; unknown fields of a known event are ignored.
- Retries apply only to requests carrying an `Idempotency-Key`, only for 429, 5xx and network errors, bounded, with the same
  key on every attempt. 4xx other than 429 is never retried. Payment methods are not retried.

## Decisions

| Name | Decision | State |
|------|----------|-------|
| result-with-key | `create_subscription` returns a result object carrying the used idempotency key; the caller may pass their own key (recommended) | implemented |
| client-config | `company_id` and the API key are client constructor parameters; the API key is the same value as `secret_key` | implemented |
| unsigned-registration | A registration failure without a signature is rejected unless `allow_unsigned=True` | implemented |
| currency-checked-by-server | `currency` is a plain string validated by the server (SDK constants know only RSD, the gateway knows RSD, RUB, EUR, USD and applies a platform-wide allow-list that answers 422) | implemented |
| unknown-event | An unknown webhook event is returned as `UnknownSubscriptionEvent` instead of raising | implemented |
| retry-502 | 502 is retried like any 5xx, keyed requests only, bounded | implemented |
| redirect-form | The wire type `iframe` is a redirect target, so the SDK names the model `RedirectForm` and the helper renders a redirect (page with a link and an auto-redirect), not an `<iframe>`; the wire value `iframe` is still accepted. Reason: nothing in the API says the page is embeddable, and hosted payment pages commonly refuse framing | implemented |
| management-by-api-key | Merchants manage subscriptions (detail, list, pause, resume, cancel, payments) with the platform API key as well as from the dashboard; the gateway adds an external route for each operation and the SDK calls those. Decided 2026-10-08; the SDK methods wait for the gateway change | agreed, blocked on the gateway |
| no-standalone-verify | The signature check is not a public function: `parse_subscription_webhook` and `parse_registration_failed` already verify, and a second entry point would invite reading the body without the checks. A merchant who queues webhooks passes the raw body and the `X-Signature` value to the worker and calls the parser there. Revisit if a real need appears, under a name that cannot be mistaken for the payment callback check | decided |

"Assumed" means: agreed as the working choice on 2026-10-08, not built yet, to be confirmed or changed. "Implemented" means the code follows it. Both stay open to change; change it here first.

## Planned: subscription management (blocked on the gateway)

Merchants will manage subscriptions from their own code with the same platform API key, as well as from the dashboard
(decision `management-by-api-key`). Today these operations need a dashboard session and are not reachable with an API key
at all, because the gateway checks the session before the request reaches the service. So for every operation the gateway
gets a second, external route next to the dashboard one (as a payment session's refund and status already have), both
served by the same service, and the SDK methods call the external routes with `company_api_key`. Until those routes exist
the SDK has no management methods.

Operations: the detail of a subscription, a list with filters, pause, resume, cancel (optionally refunding the last charge)
and the payments of a subscription. Method names, signatures, models and errors are agreed here before they are written.
Requirements already known: a subscription of another company is refused (HTTP 403); an illegal change of status must be
distinguishable from a network error; reads are not retried without a key, a change that carries an `Idempotency-Key` is.

## Open questions

- Whether test and production use separate platforms and keys.

## Notes from the dashboard

- Where a merchant finds their `company_id`: the Company info page of the dashboard shows it, read-only and copyable, at the
  right edge of the header strip that holds the company name, PIB and MB, for every member of the company. The README and the
  examples say so. (The key alone already identifies the company, so the new external routes for managing subscriptions may
  leave `company_id` out of their path.)
- Subscriptions are switched on for a company by Polako, not by the merchant; until then `create_subscription` raises
  `ConflictError`. The README says so.

## Change log

| Date | Change |
|------|--------|
| 2026-10-08 | v0.1: initial draft from the gateway contract and the agreed merchant example |
| 2026-10-08 | v0.2: checked against the gateway. The `iframe` form type turned out to be a redirect URL, so the model is named `RedirectForm` and is rendered as a redirect, not an iframe. Corrected the currency note: the allow-list is platform-wide (set by the platform operator), not per company, and answers 422. Contract notes added: `callback_url` is set in the platform settings; `company_id` is not shown in the platform settings |
| 2026-10-08 | v0.3: exceptions, retry gate, aliases, models and `create_subscription` implemented. Added to the spec what the code now does: `ConfigurationError`, `UnknownRegistrationFormError` as the cause of a read failure, client-side argument checks, plain-decimal `amount`, immutable result, API key hidden in `repr`. No change to the agreed example or signatures |
| 2026-10-08 | v0.4: the signature check and `parse_subscription_webhook` implemented. Added to the spec: `WebhookPayloadError`, the `SubscriptionWebhookEvent` alias, the event fields, verify-before-read rule, UTF-8 only. The merchant example now reads the header with `.get("X-Signature")` and the function accepts a missing header (it raises `MissingSignatureError`), instead of a `KeyError` in the merchant's code |
| 2026-10-08 | v0.5: `parse_registration_failed` implemented, with the `allow_unsigned` policy. Added to the spec: the registration failure is a model of its own with `event = None` and `success = 0`, and the two parsers reject each other's bodies with a pointer to the right function; `success` must be 0 or false (missing accepted); `order_id` always equals `subscription_id` and is not kept; a present signature is always checked, a missing one is rejected unless `allow_unsigned=True`. Decisions that the code now follows are marked implemented |
| 2026-10-08 | v0.6: subscription management is no longer an open question. Decided that merchants manage subscriptions with the platform API key as well as from the dashboard, which needs an external route per operation in the gateway; the SDK methods are planned and wait for that change. Section Planned added, the question removed from Open questions |
| 2026-10-08 | v0.7: `render_registration_form` implemented. Added to the spec: the exact input names of a posted `form_post` (the processor's names, not the gateway's camelCase), pass-through of the provider fields, the redirect page for the `iframe` wire type, the `auto_submit` behaviour, and the safety rules (http/https address with no whitespace or control characters, escaping, one constant script, nothing loaded from elsewhere). The `redirect-form` decision is marked implemented |
| 2026-10-08 | v0.8: the README section and `examples/subscription_example.py` are written. The acceptance example moved out of this file into `examples/subscription_example.py` (one copy, checked by the documentation check, so it cannot drift from this spec unnoticed); the flow itself did not change except that the example turns every error of the SDK into an HTTP answer. The example was run end to end against the gateway emulator on Python 3.10 and 3.13 |
| 2026-10-08 | v0.9: decided not to export the signature check as a public function (decision `no-standalone-verify`). The open question about `company_id` now records what was found: the dashboard shows it nowhere, and the key already identifies the company |
| 2026-10-08 | v0.10: the open question about `company_id` now records the agreed direction: the dashboard shows it on the Company info page, at the right edge of the header strip next to PIB and MB, read-only and copyable, for every member of the company. Not built yet; the README stays as it is until it is |
| 2026-10-08 | v0.11: the dashboard shows the company ID on the Company info page, so the open question is closed and moved to a new section, Notes from the dashboard. The README and the examples now say where to find the ID, and that Polako switches subscriptions on for a company (otherwise `ConflictError`) |
