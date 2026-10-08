# python-sdk — Subscriptions: client-facing specification

**Status: DRAFT v0.3** — agreed in principle on 2026-10-08. Implemented so far: exceptions by status, the retry
gate, wire aliases, the models and `create_subscription`. Not yet: webhook parsers, form rendering helper, README and example. Scope: **creating a subscription, full cycle**
(create, render the 3DS form, receive webhooks). Subscription management is out of scope until it is decided whether merchants
should manage subscriptions from their own code (see Open questions).

## How to use this document

This is the source of truth for the subscription surface of the SDK. The order of work is outside-in:

1. the interface and the merchant example below are agreed first;
2. tests and implementation follow them; if the implementation cannot match, the **spec is changed first** (see the
   change log), then the code;
3. `examples/` and the README sections are written from it and must match it (the docs checker verifies signatures).

Any deviation from this file is a spec change: edit the file, add a change-log row, then change the code.

## Scope

In: authentication of the create call, `create_subscription`, models for the request, the response and the three
registration forms, form rendering helper, webhook parsers (four lifecycle events and the registration-failed
notification), exceptions by HTTP status, retries for keyed requests.

Out (open): management methods (detail, list, pause, resume, cancel, payments), retries for payment methods,
unification of the two signature schemes, `SubscriptionStatus` / `ChargeAttemptStatus` enums, live checks on production.

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
- Registration failure goes to the `errorUrl` of the subscription: no `event` field; `order_id`, `subscription_id`,
  `merchant_subscription_ref`, `success` (0), `error_message`, `provider_name`; one attempt, 10 s timeout, no retries.
  Signed with the same scheme when the subscription is linked to a platform (always true for subscriptions created with a
  platform API key), otherwise sent without `X-Signature`.
- Cancelling is console-only (JWT), so the end-to-end example ends at receiving the `cancelled` webhook.

## Target merchant code (acceptance example)

```python
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from polako.sdk import (
    BillingInterval, ChargeFailed, ChargeSucceeded, ConflictError, PolakoClient, RateLimitedError,
    WebhookSignatureError, parse_registration_failed, parse_subscription_webhook, render_registration_form,
)

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000000")  # your company ID
API_KEY = "your-secret-key"                                # the same API key as for payments

app = FastAPI()


@app.post("/subscribe")
async def subscribe():
    key = str(uuid4())  # save it with your order before the call: a retry after a crash then reuses it
    async with PolakoClient(test_env=True, company_id=COMPANY_ID, api_key=API_KEY) as client:
        try:
            created = await client.create_subscription(
                customer_email="jane.smith@example.com",
                amount=Decimal("990.00"),
                currency="RSD",
                billing_interval=BillingInterval.MONTHLY,
                merchant_subscription_ref="plan-pro-monthly",
                success_url="https://shop.example.com/subscribe/success",
                cancel_url="https://shop.example.com/subscribe/cancel",
                error_url="https://shop.example.com/polako/subscription-error",
                idempotency_key=key,
            )
        except ConflictError:
            raise HTTPException(409, "You already have this subscription")
        except RateLimitedError as e:
            raise HTTPException(429, f"Try again in {e.retry_after} s")
    return HTMLResponse(render_registration_form(created.registration_form))  # customer goes through 3DS


@app.post("/polako/subscription-webhook")
async def subscription_webhook(request: Request):
    try:
        event = parse_subscription_webhook(await request.body(), request.headers["X-Signature"], API_KEY)
    except WebhookSignatureError:
        raise HTTPException(400, "invalid signature")
    if isinstance(event, ChargeSucceeded):
        ...  # extend access: event.subscription_id, event.amount, event.charged_at
    elif isinstance(event, ChargeFailed):
        ...  # event.error_class
    return {"status": "ok"}


@app.post("/polako/subscription-error")
async def subscription_error(request: Request):
    failure = parse_registration_failed(await request.body(), request.headers.get("X-Signature"), API_KEY)
    ...  # failure.subscription_id, failure.error_message
    return {"status": "ok"}
```

## Interface

| Item | Signature |
|------|-----------|
| Client | `PolakoClient(timeout=30.0, test_env=False, company_id: UUID \| None = None, api_key: str \| None = None)`; payment methods unchanged |
| Create | `await create_subscription(*, customer_email, amount: Decimal, currency: str, billing_interval: BillingInterval, merchant_subscription_ref, success_url, cancel_url, error_url, idempotency_key: str \| None = None) -> SubscriptionCreated` |
| Result | `SubscriptionCreated`: `subscription_id`, `registration_form`, `idempotency_key` (the one used, also when generated) |
| Form | `registration_form` is `FormPost`, `HppFormPost` or `RedirectForm` (wire `type` is `iframe`); `render_registration_form(form, *, auto_submit=True) -> str` |
| Events | `parse_subscription_webhook(body: bytes \| str, signature: str, api_key: str)` returns `ChargeSucceeded`, `ChargeFailed`, `DroppedExternally`, `SubscriptionCancelled` or `UnknownSubscriptionEvent` |
| Registration failure | `parse_registration_failed(body, signature: str \| None, api_key, *, allow_unsigned=False) -> RegistrationFailed` with `signature_verified` |
| Exceptions | `UnauthorizedError` (401), `ForbiddenError` (403), `ConflictError` (409), `RequestValidationError` (422), `RateLimitedError` (429, `retry_after`), `ServerError` (5xx), all subclasses of `HttpRequestError`; `ConfigurationError` (missing `company_id` or `api_key`, a `ValueError`); `UnknownRegistrationFormError` (a `ValueError`; surfaces as the `__cause__` of the `HttpRequestError` the client raises when it cannot read the response); `WebhookSignatureError`, `MissingSignatureError` |

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
- Retries apply only to requests carrying an `Idempotency-Key`, only for 429, 5xx and network errors, bounded, with the same
  key on every attempt. 4xx other than 429 is never retried. Payment methods are not retried.

## Decisions

| Name | Decision | State |
|------|----------|-------|
| result-with-key | `create_subscription` returns a result object carrying the used idempotency key; the caller may pass their own key (recommended) | assumed |
| client-config | `company_id` and the API key are client constructor parameters; the API key is the same value as `secret_key` | assumed |
| unsigned-registration | A registration failure without a signature is rejected unless `allow_unsigned=True` | assumed |
| currency-checked-by-server | `currency` is a plain string validated by the server (SDK constants know only RSD, the gateway knows RSD, RUB, EUR, USD and applies a platform-wide allow-list that answers 422) | assumed |
| unknown-event | An unknown webhook event is returned as `UnknownSubscriptionEvent` instead of raising | assumed |
| retry-502 | 502 is retried like any 5xx, keyed requests only, bounded | assumed |
| redirect-form | The wire type `iframe` is a redirect target, so the SDK names the model `RedirectForm` and the helper renders a redirect (page with a link and an auto-redirect), not an `<iframe>`; the wire value `iframe` is still accepted. Reason: nothing in the API says the page is embeddable, and hosted payment pages commonly refuse framing | assumed |

"Assumed" means: agreed as the working choice on 2026-10-08, to be confirmed or changed; change it here first.

## Open questions

- Should a merchant manage subscriptions from their own code (pause, resume, cancel, read)? Today these operations need a
  dashboard session token and are dashboard operations. Options: dashboard only (nothing in the SDK), SDK methods taking a
  ready token, or the gateway accepts the platform API key for them.
- To confirm before the README is written: where a merchant finds their `company_id` (it is part of the create URL; the
  platform settings show the platform ID and the API key), and whether test and production use separate platforms and keys.

## Change log

| Date | Change |
|------|--------|
| 2026-10-08 | v0.1: initial draft from the gateway contract and the agreed merchant example |
| 2026-10-08 | v0.2: checked against the gateway. The `iframe` form type turned out to be a redirect URL, so the model is named `RedirectForm` and is rendered as a redirect, not an iframe. Corrected the currency note: the allow-list is platform-wide (set by the platform operator), not per company, and answers 422. Contract notes added: `callback_url` is set in the platform settings; `company_id` is not shown in the platform settings |
| 2026-10-08 | v0.3: exceptions, retry gate, aliases, models and `create_subscription` implemented. Added to the spec what the code now does: `ConfigurationError`, `UnknownRegistrationFormError` as the cause of a read failure, client-side argument checks, plain-decimal `amount`, immutable result, API key hidden in `repr`. No change to the agreed example or signatures |
