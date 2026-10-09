# python-sdk — Subscriptions: client-facing specification

**Status: DRAFT v0.17** — agreed in principle on 2026-10-08. Implemented so far: exceptions by status, the retry
gate, wire aliases, the models, `create_subscription`, the webhook signature check, `parse_subscription_webhook` and
`parse_registration_failed` and `render_registration_form`, plus the README section and the example. Scope: **creating a subscription, full cycle**
(create, render the 3DS form, receive webhooks). Subscription management (read, list, pause, resume, cancel) is implemented too, against the server routes that accept the
platform API key (see Subscription management).

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
notification), exceptions by HTTP status, retries for keyed requests, management methods (`get_subscription`,
`list_subscriptions`, `pause_subscription`, `resume_subscription`, `cancel_subscription`), their models and enums,
`NotFoundError`.

Out: retries of management methods (decision `management-no-retry`), retries for payment methods,
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
- Cancelling is console-only (JWT) in the released server, so the end-to-end example ends at receiving the `cancelled`
  webhook. The routes that accept the platform API key for it are built and wait for a release (see Planned).

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
| Read | `await get_subscription(subscription_id: UUID \| str) -> SubscriptionDetails` |
| List | `await list_subscriptions(*, status: Iterable[SubscriptionStatus \| str] \| None = None, billing_interval: Iterable[BillingInterval \| str] \| None = None, search: str \| None = None, created_from: date \| datetime \| None = None, created_to: date \| datetime \| None = None, sort_by: str \| None = None, sort_order: str \| None = None, limit: int = 10, offset: int = 0) -> SubscriptionPage` |
| Change | `await pause_subscription(subscription_id)`, `await resume_subscription(subscription_id)`, `await cancel_subscription(subscription_id)`, each returns `None` |
| Management results | `SubscriptionPage`: `items` (a tuple of `SubscriptionSummary`), `total`, `limit`, `offset`. `SubscriptionSummary`: `id`, `customer_id`, `customer_email`, `merchant_subscription_ref`, `amount` (`Decimal`), `currency`, `billing_interval`, `status`, `next_charge_at`, `last_charged_at`, `created_at`. `SubscriptionDetails`: the same fields except `customer_id` and `customer_email`, which are inside `customer` (`SubscriptionCustomer`: `id`, `external_customer_id`, `email`), plus `saved_card` (`SavedCard` or `None`: `id`, `masked_pan`, `card_brand`, `pan_expiry`, `status`; never a token), `anchor_at`, `failed_charge_count`, `last_failed_charge_at`, `charge_history` (a tuple of `ChargeAttempt`, newest first: `id`, `charge_date`, `order_id`, `status`, `amount`, `result_code`, `error_class`, `error_message`, `retry_count`, `next_retry_at`, `created_at`, `updated_at`, `payment_session_id`) and `events` (a tuple of `SubscriptionEvent`, oldest first: `id`, `event_type`, `payload`, `created_at`). All immutable |
| Enums | `SubscriptionStatus` (`pending_registration`, `registration_failed`, `active`, `past_due`, `paused`, `cancelled`) and `ChargeAttemptStatus` (`pending`, `succeeded`, `failed`), both `str` enums, public |
| Exceptions | `UnauthorizedError` (401), `ForbiddenError` (403), `NotFoundError` (404, new in v0.13), `ConflictError` (409), `RequestValidationError` (422), `RateLimitedError` (429, `retry_after`), `ServerError` (5xx), all subclasses of `HttpRequestError`; `ConfigurationError` (missing `company_id` or `api_key`, a `ValueError`); `UnknownRegistrationFormError` (a `ValueError`; surfaces as the `__cause__` of the `HttpRequestError` the client raises when it cannot read the response); `WebhookSignatureError`, `MissingSignatureError` (a `WebhookSignatureError`), `WebhookPayloadError` (a `ValueError`: the signed body is not JSON, not an object, has no event name, or a field is missing or malformed) |

Behaviour rules:
- `create_subscription` without `company_id` or `api_key` raises a clear configuration error before any request.
- The `company_api_key` header is set only on subscription calls; signed payment calls are unchanged.
- The API key never appears in logs, `repr` or exception text.
- Webhook signatures are verified over the raw body exactly as received, with `hmac.compare_digest`; a forged signature raises
  `WebhookSignatureError` (never `AssertionError`).
- Arguments are checked before any request and raise `ValueError`: `customer_email` contains `@` and no spaces; `amount` is a
  finite `Decimal` greater than zero with at most two decimal places (floats are rejected; the server keeps cents, so
  a third decimal would be silently rounded); `currency` is not empty; `billing_interval` is a
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
  an `<iframe>`. With `auto_submit` on a posted form submits itself with one constant script (it calls the submit method of the
  form element itself, so a provider field named `submit` or `action` cannot shadow it) and always shows a visible button
  (not inside `<noscript>`: a page policy that blocks the inline script leaves scripting on, and a `<noscript>` button would
  never show); with it off the page has the same button and no script (for sites that forbid inline scripts).
- The helper refuses what could be turned against the customer: the address must be an http or https URL with a host, and
  must contain no whitespace or control characters (`ValueError`); every name, value and address is HTML-escaped; the
  script holds no data from the form; the page loads nothing from elsewhere; anything that is not a registration form is a
  `TypeError`. The input names for `FormPost` are taken from the working reference page of the gateway's own integration
  tools; confirm them against the staging environment before relying on them in production.
- A time is read the same way everywhere, in webhooks and in management results, on every supported Python version: ISO 8601
  with a trailing `Z`, a numeric offset (`+02:00`, `+0200`, `+02`) or none (then UTC), with any number of fraction digits
  (kept to the microsecond: digits beyond the sixth are cut off, not rounded), and the seconds may be left out (`10:20`).
  Only the digits 0-9 are digits of a time. The result is always timezone-aware. A date with no time of day is not a time and is refused.
  The `timestamp` of a payment callback of schema 1.1 is read the same way; that of the legacy format has no zone and stays
  naive. An unknown event name is returned, not raised; unknown
  fields of a known event are ignored.
- An answer to a subscription request that lacks the subscription ID or the registration form, or holds a value of the wrong
  kind, is an `HttpRequestError` whose cause is the reason; no result is built from half an answer.
- Retries apply only to requests carrying an `Idempotency-Key`, only for 429, 500, 502, 503 and 504 and for network errors that a repeat can cure
  (timeouts, connection and protocol failures), bounded, with the same key on every attempt. 501, 505, an unsupported or refused
  address and the like are never retried. 4xx other than 429 is never retried. Payment methods are not retried. Management methods are not
  retried either (decision `management-no-retry`).
- A read timeout is retried too. That is safe only because the server replays a request with a key it has already seen, so
  the repeat returns the same subscription instead of creating a second one. Every attempt counts against the endpoint's
  limit of 20 requests per 60 seconds. There is no overall deadline: with the defaults (30 s timeout, three attempts, waits of
  0.5 s and 1 s, or the server's `Retry-After` up to 8 s each) the time of a failing call lies between two ends. A call that
  fails fast (three answers of 503) ends in about 1.5 s. The slow end is three attempts that each run into the timeout, plus
  two waits of 8 s: about 106 s if each attempt lasts one timeout, and more, up to two minutes or longer, because `httpx`
  applies the timeout to each phase of one attempt (connect, write, read) and name resolution adds its own time. A merchant
  who sets a deadline of their own should set it well above the slow end.
- Management methods need `company_id` and `api_key` like `create_subscription` and raise `ConfigurationError`
  before any request otherwise; the key goes in the `company_api_key` header and nothing else is signed. Arguments are checked
  before any request and raise `ValueError`: `subscription_id` is a `UUID` or a string that is one; `limit` is 1 to 100;
  `offset` is not negative; `sort_by` is one of `created_at`, `next_charge_at`, `last_charged_at`, `amount`, `status`;
  `sort_order` is `asc` or `desc`; `search` is not blank when given; `status` and `billing_interval` hold members of the
  enums or their string values; `created_from` and `created_to` are a `date` or a timezone-aware `datetime` (a naive
  `datetime` is rejected, not guessed), sent as ISO 8601, both bounds inclusive. `search` is matched by the server against
  the customer's email, the merchant reference and the id. Several `status` or `billing_interval` values match any of them.
- Management results are read tolerantly: an unknown value of a known enum field (a status, an interval, a charge status)
  stays the raw string instead of failing the call, and unknown fields are ignored; a field that is missing or of the wrong
  type is an `HttpRequestError` whose cause is the decoding error, as for `create_subscription`. Money is a `Decimal`
  whether the server sends it as a string or a number; times are timezone-aware `datetime` values; `charge_date` is a `date`.
- `pause_subscription`, `resume_subscription` and `cancel_subscription` answer nothing on success. A status that does not
  allow the change (pause needs `active`, resume needs `paused`, a cancelled subscription accepts nothing) and subscriptions
  being switched off for the company are both a `ConflictError`; the message of the server says which. A network error is an
  `HttpClientError` and the change may or may not have been applied: read the subscription with `get_subscription` before
  repeating it.

## Decisions

| Name | Decision | State |
|------|----------|-------|
| result-with-key | `create_subscription` returns a result object carrying the used idempotency key; the caller may pass their own key (recommended) | implemented |
| client-config | `company_id` and the API key are client constructor parameters; the API key is the same value as `secret_key` | implemented |
| unsigned-registration | A registration failure without a signature is rejected unless `allow_unsigned=True` | implemented |
| currency-checked-by-server | `currency` is a plain string validated by the server (SDK constants know only RSD, the gateway knows RSD, RUB, EUR, USD and applies a platform-wide allow-list that answers 422) | implemented |
| unknown-event | An unknown webhook event is returned as `UnknownSubscriptionEvent` instead of raising | implemented |
| retry-502 | 502 is retried together with 429, 500, 503 and 504, keyed requests only, at most three attempts; 501, 505 and the other statuses are not retried | implemented |
| redirect-form | The wire type `iframe` is a redirect target, so the SDK names the model `RedirectForm` and the helper renders a redirect (page with a link and an auto-redirect), not an `<iframe>`; the wire value `iframe` is still accepted. Reason: nothing in the API says the page is embeddable, and hosted payment pages commonly refuse framing | implemented |
| management-by-api-key | Merchants manage subscriptions (detail, list, pause, resume, cancel) with the platform API key as well as from the dashboard. One route per operation serves both: a dashboard login is used when the request carries one, otherwise the API key, and a login wins over a key sent beside it. The SDK methods call those routes with `company_api_key`. Decided 2026-10-08, route design 2026-10-09; the server side is built and the SDK methods are implemented against it | implemented; the server release is pending |
| no-standalone-verify | The signature check is not a public function: `parse_subscription_webhook` and `parse_registration_failed` already verify, and a second entry point would invite reading the body without the checks. A merchant who queues webhooks passes the raw body and the `X-Signature` value to the worker and calls the parser there. Revisit if a real need appears, under a name that cannot be mistaken for the payment callback check | decided |
| management-no-retry | Management methods are never retried, neither the changes nor the reads. The server takes no `Idempotency-Key` on pause, resume and cancel, and a repeat after a lost response would meet the new status and answer 409, which cannot be told from a real refusal, so a change that worked would look like a failure. The caller reads the subscription and decides. Reads could be retried safely, but the retry rules are shared with the payment methods and are being discussed separately, so they stay as they are. Revisit when the server accepts an `Idempotency-Key` on the changes | implemented |
| management-not-found | A 404 is a `NotFoundError`, a subclass of `HttpRequestError`, so that "no such subscription" is not caught together with every other HTTP failure | implemented |
| management-one-page | `list_subscriptions` returns one page (`limit`, `offset`) as a `SubscriptionPage`; there is no iterator. One can be added later without changing it | implemented |
| tolerant-reading | Management results keep an unknown enum value as the raw string and ignore unknown fields, so that a status added by the server does not break a merchant's listing | implemented |

"Assumed" means: agreed as the working choice on 2026-10-08, not built yet, to be confirmed or changed. "Implemented" means the code follows it. Both stay open to change; change it here first.

## Subscription management (server routes built; SDK methods implemented)

Merchants will manage subscriptions from their own code with the same platform API key, as well as from the dashboard
(decision `management-by-api-key`). In the released server these operations need a dashboard session. The new server
code serves the same routes to both kinds of caller: `GET /v1/company/{company_id}/subscriptions` (list), `GET
.../{subscription_id}` (detail), and `PATCH .../{subscription_id}/pause`, `/resume`, `/cancel` (status 204). A request
that carries the dashboard's login is treated as a dashboard call; one without it must carry `company_api_key`, which
must belong to the company in the path. The SDK methods call these routes with `company_api_key`; their signatures,
models, errors and rules are in Interface and Behaviour rules above. They work against a server that has the new routes.

What the server answers, for an API key: 401 for a missing or unknown key, 403 for the key of another company or for a
subscription of another company, 404 for an unknown subscription, 409 when subscriptions are switched off for the company
or the status does not allow the change (pause needs `active`, resume needs `paused`, a cancelled subscription accepts
nothing), 422 for a malformed identifier. Reading is allowed even when subscriptions are switched off. A key has full
authority over its company's subscriptions.

Operations: the detail of a subscription (which carries the charge history and the event journal, so there is no separate
route for the payments of a subscription), a list with filters, pause, resume and cancel. Cancelling does not refund; a
refund goes through the payment refund: the `payment_session_id` of a charge in the history is what `refund_session`
needs. Requirements: a subscription of another company is refused (HTTP 403); an illegal change of status must be
distinguishable from a network error; none of the management methods is retried (decision `management-no-retry`).

## Open questions

- Whether test and production use separate platforms and keys.

## Notes from the dashboard

- Where a merchant finds their `company_id`: the Company info page of the dashboard shows it, read-only and copyable, at the
  right edge of the header strip that holds the company name, PIB and MB, for every member of the company. The README and the
  examples say so. (The key alone already identifies the company, but the management routes keep `company_id` in their path
  and check that it matches the key.)
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
| 2026-10-09 | v0.12: the design of the management routes is settled: one route per operation serves both the dashboard login and the platform API key (a login wins over a key sent beside it), instead of a second external route per operation. Decision `management-by-api-key` and section Planned rewritten with the routes, the answers for an API key and the facts found while building it: no separate payments route (the detail carries the charge history), cancel does not refund, reading is not gated by the switch, the management routes take no `Idempotency-Key` yet. The server side is built and waits for a release, so the SDK methods are still not written |
| 2026-10-09 | v0.13: the interface of subscription management is agreed: `get_subscription`, `list_subscriptions` (one page, filters, sorting, `limit`/`offset`), `pause_subscription`, `resume_subscription`, `cancel_subscription` (return `None`); the result models (`SubscriptionPage`, `SubscriptionSummary`, `SubscriptionDetails` with `SubscriptionCustomer`, `SavedCard`, `ChargeAttempt`, `SubscriptionEvent`), the public enums `SubscriptionStatus` and `ChargeAttemptStatus`, and `NotFoundError` for 404. New decisions `management-no-retry` (no retries for any management method, the reason being that a repeated change meets its own result as a 409), `management-not-found`, `management-one-page`, `tolerant-reading`. Interface, Behaviour rules, Scope and the management section updated; nothing is built yet |
| 2026-10-09 | v0.14: the management methods are implemented as agreed in v0.13: `get_subscription`, `list_subscriptions`, `pause_subscription`, `resume_subscription`, `cancel_subscription`, the result models (`SubscriptionPage`, `SubscriptionSummary`, `SubscriptionDetails` and its parts), the enums `SubscriptionStatus` and `ChargeAttemptStatus` and `NotFoundError`. Models are grouped by operation (`_subscription_list.py`, `_subscription_detail.py`), the argument checks live in `_validation.py` and only check, the reading of server values in `_decoding.py`. Added to the spec what the build settled: 400 stays a plain `HttpRequestError` (the server answers it to a filter or sort field it does not accept); `SubscriptionDetails` has no `customer_id` or `customer_email` of its own; an empty collection for a filter is refused; a time bound is sent in UTC to the second. The README section, `examples/subscription_management_example.py` and the CHANGELOG are written; the code of the README and of the example was run against the gateway emulator. The server release is the only thing pending |
| 2026-10-09 | v0.15: changes from the review of the pull request, each checked against the code first. Times are read by one reader for webhooks and management results: a time without a zone is UTC (a webhook's `charged_at` used to come back without a zone; this is a behaviour change that can break a merchant who compares it with a naive `utcnow()`, which is now a `TypeError`), a date with no time of day is refused, the `timestamp` of a schema 1.1 payment callback is read by the same reader (the legacy callback format stays without a zone), and the fraction and the offset may be written in any of the usual ways (Python 3.10 could not read some of them). A subscription answer without an ID or a form, or with a malformed one, is an `HttpRequestError` at once instead of a result full of empty values. The self-submitting form calls the form element's own submit method, so a provider field named `submit` cannot break it. Retries are limited to 429, 500, 502, 503, 504 and to network errors a repeat can cure. `amount` may have at most two decimal places (the server stores cents and rounded a third decimal silently). Decided to leave as it is: the address of the registration form may be http or https; `success` of a failure notification stays `0` or `false`; `company_api_key` keeps its name (the platform's proxy accepts underscores) |
| 2026-10-09 | v0.16: second round of the review of the pull request, each remark checked against the code first. Retries: the decision row `retry-502` no longer says "any 5xx" (501 and 505 are not retried), and the spec now says that a read timeout is retried (safe because the server replays a known key), that every attempt counts against the limit of 20 requests per 60 seconds, and that there is no overall deadline (about 106 s at worst with the defaults). The lines about three attempts for 5xx in the webhook section and in the architecture note describe the gateway delivering webhooks, not the SDK, and stay. Times: the seconds may be left out, only the digits 0-9 are digits, and digits beyond the sixth of a fraction are cut off, not rounded. A schema 1.1 payment callback has an aware time and the legacy one a naive time; the legacy format has no zone and the SDK cannot know which, so it stays naive and the difference is written in the `PaymentCallback.datetime` documentation and the changelog. The rendered page always shows its button (not inside `<noscript>`), because a page policy that blocks the inline script leaves scripting on and a `<noscript>` button would never appear. The message for an `amount` with a third decimal says to round to cents first. Changelog: everything about subscriptions is new in the unreleased version, so the notes about reading times and about `amount` are part of the new methods and not a change of released behaviour; only the 404 error class and the time of a schema 1.1 payment callback change something a released version did. The documentation check fails on a block that is never closed and treats a fence indented by four columns as a fence only inside a list item |
| 2026-10-09 | v0.17: third round of the review of the pull request, each remark checked against the code first. The time of a failing call is stated as a range and not as a minimum: about 1.5 s when the gateway answers 503 three times in a row, about 106 s when each attempt runs into the timeout and the waits are the longest, and more than that because the timeout of `httpx` applies to each phase of an attempt; this replaces "at least about 106 s" of v0.16, and the README, the changelog and the docstring say "two minutes or more" for the slow end. The documentation check (a tool, not a part of the contract) now reads the language of a fence as its first word, case-insensitive (`python`, `Python`, `py`, `python3`, `py3`; `pycon` is a console session and not code), takes headings indented by up to three spaces, reads a fence inside a quote, and leaves the tabs of a block as they are written so that the hash follows what a reader copies |
