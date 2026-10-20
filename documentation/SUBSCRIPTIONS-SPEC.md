# python-sdk — Subscriptions: client-facing specification

**Status: DRAFT v0.43** — agreed in principle on 2026-10-08. Implemented: creating a subscription (create, render the 3DS
form, receive webhooks) and managing it (read, list, pause, resume, cancel) with the platform API key.

## How to use this document

This is the source of truth for the subscription surface of the SDK. Work goes outside-in: the interface and the merchant
example (`examples/subscription_example.py`) are agreed first, then the implementation; `examples/` and the README are
written from this file and must match it. A deviation is a spec change: edit this file, add a change-log row, then change
the code.

## Scope

In: authentication of the create call, `create_subscription`, models for the request, the response and the three
registration forms, the form rendering helper, webhook parsers (four lifecycle events and the registration-failed
notification), exceptions by HTTP status, retries for keyed requests, the management methods (`get_subscription`,
`list_subscriptions`, `pause_subscription`, `resume_subscription`, `cancel_subscription`), their models and enums.

Out: retries of management methods and of payment methods, unification of the two signature schemes, live checks on production, a public
`verify_webhook_signature` (see Decisions).

## Gateway contract (verified 2026-10-08)

- `POST /v1/company/{company_id}/subscriptions`, status 201. Headers: `company_api_key` (the API key of the platform, the
  same value that signs payment requests) and a mandatory `Idempotency-Key`. A repeat with the same key returns the
  original response.
- Body (the server accepts camelCase and snake_case, responses are camelCase only): `customerEmail`, `amount` (> 0),
  `currency`, `billingInterval` (`daily` `weekly` `monthly` `quarterly` `yearly`), `merchantSubscriptionRef` (1-128 chars),
  `successUrl`, `cancelUrl`, `errorUrl` (http or https).
- Response: `subscriptionId` and `registrationForm`, a union discriminated by `type`: `form_post` (`action`, `version`,
  `merchantId`, `terminalId`, `totalAmount`, `currency`, `locale`, `purchaseTime`, `orderId`, `signature`), `hpp_form_post`
  (`action`, `fields`: dict of strings), `iframe` (`action`). Despite its name, `iframe` carries only a redirect address:
  it is a redirect target, not an embeddable page.
- Errors: 401 (missing or unknown key), 403 (key belongs to another company), 409 (subscriptions disabled for the company,
  or the customer already has a live subscription for the same `merchantSubscriptionRef`), 422 (invalid fields or key, and
  a currency outside the platform-wide allow-list), 502 (the provider rejected the card registration request).
- Lifecycle webhooks go to `credentials["callback_url"]` of the platform (set in the platform settings in the dashboard; optional for generic platforms, required for one platform type):
  signed with HMAC-SHA256 over the raw compact JSON body with sorted keys, hex digest in `X-Signature`, key = the platform
  API key. Three attempts (1 s, 2 s back-off) on 5xx or network errors, 4xx is final.
  - `charge_succeeded`: `event`, `subscription_id`, `merchant_subscription_ref`, `amount` (string), `currency`, `charged_at` (ISO)
  - `charge_failed`: `event`, `subscription_id`, `merchant_subscription_ref`, `error_class`
  - `dropped_externally`, `cancelled`: `event`, `subscription_id`, `merchant_subscription_ref`
- Registration failure goes to the `errorUrl` of the subscription: no `event` field; `order_id` (always equal to
  `subscription_id`), `subscription_id`, `merchant_subscription_ref`, `success` (always 0), `error_message`,
  `provider_name`; one attempt, 10 s timeout, no retries. Signed with the same scheme when the subscription is linked to a
  platform (always true for subscriptions created with a platform API key), otherwise sent without `X-Signature`.

## Acceptance example

`examples/subscription_example.py` is a complete merchant server: create a subscription, return the card registration page,
read the webhooks and the registration-failure notification, with the SDK's errors turned into HTTP answers. The
`Subscriptions` section of the README shows the same flow in pieces. A change to the flow is made here first.

## Interface

| Item | Signature |
|------|-----------|
| Client | `PolakoClient(timeout=30.0, test_env=False, company_id: UUID \| None = None, api_key: str \| None = None)`; payment methods unchanged |
| Create | `await create_subscription(*, customer_email, amount: Decimal, currency: str, billing_interval: BillingInterval, merchant_subscription_ref, success_url, cancel_url, error_url, idempotency_key: str \| UUID \| None = None) -> SubscriptionCreated` |
| Result | `SubscriptionCreated`: `subscription_id`, `registration_form`, `idempotency_key` (the one used, also when generated) |
| Form | `registration_form` is `FormPost`, `HppFormPost` or `RedirectForm` (wire `type` is `iframe`); `render_registration_form(form, *, auto_submit=True) -> str` returns a complete HTML page for the merchant to return as an HTML response |
| Events | `parse_subscription_webhook(body: bytes \| str, signature: str \| None, api_key: str)` returns `ChargeSucceeded` (`amount`, `currency`, `charged_at`), `ChargeFailed` (`error_class`), `DroppedExternally`, `SubscriptionCancelled` or `UnknownSubscriptionEvent` (`event`, `data`); all carry `subscription_id` (a `UUID`) and `merchant_subscription_ref` (may be `None`), are immutable, and are covered by the `SubscriptionWebhookEvent` type alias |
| Registration failure | `parse_registration_failed(body, signature: str \| None, api_key, *, allow_unsigned=False) -> RegistrationFailed`: `subscription_id` (a `UUID`), `merchant_subscription_ref`, `error_message`, `provider_name` (each may be `None` but the id), `signature_verified`; immutable. It has no event (`event = None`, unlike every lifecycle event) and `success = 0`; `order_id` is not kept because it always equals `subscription_id` |
| Read | `await get_subscription(subscription_id: UUID \| str) -> SubscriptionDetails` |
| List | `await list_subscriptions(*, status: Iterable[SubscriptionStatus \| str] \| None = None, billing_interval: Iterable[BillingInterval \| str] \| None = None, search: str \| None = None, created_from: date \| datetime \| None = None, created_to: date \| datetime \| None = None, sort_by: str \| None = None, sort_order: str \| None = None, limit: int = 10, offset: int = 0) -> SubscriptionPage` |
| Change | `await pause_subscription(subscription_id)`, `await resume_subscription(subscription_id)`, `await cancel_subscription(subscription_id)`, each returns `None` |
| Management results | `SubscriptionPage`: `items` (a tuple of `SubscriptionSummary`), `total`, `limit`, `offset`. `SubscriptionSummary`: `id`, `customer_id`, `customer_email`, `merchant_subscription_ref`, `amount` (`Decimal`), `currency`, `billing_interval`, `status`, `next_charge_at`, `last_charged_at`, `created_at`. `SubscriptionDetails`: the same fields except `customer_id` and `customer_email`, which are inside `customer` (`SubscriptionCustomer`: `id`, `external_customer_id`, `email`), plus `saved_card` (`SavedCard` or `None`: `id`, `masked_pan`, `card_brand`, `pan_expiry`, `status`; never a token), `anchor_at`, `failed_charge_count`, `last_failed_charge_at`, `charge_history` (a tuple of `ChargeAttempt`, newest first: `id`, `charge_date`, `order_id`, `status`, `amount`, `result_code`, `error_class`, `error_message`, `retry_count`, `next_retry_at`, `created_at`, `updated_at`, `payment_session_id`) and `events` (a tuple of `SubscriptionEvent`, oldest first: `id`, `event_type`, `payload`, `created_at`). All immutable |
| Enums | `SubscriptionStatus` (`pending_registration`, `registration_failed`, `active`, `past_due`, `paused`, `cancelled`) and `ChargeAttemptStatus` (`pending`, `succeeded`, `failed`), both `str` enums, public |
| Exceptions | Per status, all subclasses of `HttpRequestError`: `UnauthorizedError` (401), `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409), `RequestValidationError` (422), `RateLimitedError` (429, `retry_after`), `ServerError` (5xx). `HttpRequestError` is a subclass of `HttpClientError`, the base of every HTTP failure; a failure before an answer arrived is a plain `HttpClientError`, so `except HttpClientError` catches status errors too. Subclasses of `ValueError`: `ConfigurationError` (missing `company_id` or `api_key`, or an `api_key` that cannot be sent as a header), `InvalidArgumentError` (any argument check, raised before anything is sent), `InvalidHeaderValueError` (an `InvalidArgumentError`: an `idempotency_key` or a header that cannot be sent), `UnknownRegistrationFormError` (the `__cause__` of the `HttpRequestError` raised when a response cannot be read), `WebhookPayloadError` (the signed body is not JSON, not an object, has no event name, or a field is missing or malformed). `WebhookSignatureError` and its subclass `MissingSignatureError` |

## Behaviour rules

### Credentials and arguments

- A subscription call (create or management) without `company_id` or `api_key` raises `ConfigurationError` before any request;
  payment calls need neither.
- The `company_api_key` header is set only on subscription calls; signed payment calls are unchanged.
- The API key never appears in logs, `repr` or exception text, and nothing is chained to its errors.
- `api_key` is a string of printable ASCII without whitespace at either end (a key read from a file often ends with a
  newline); otherwise `ConfigurationError`, with a message that says whether the key is not a string or cannot be sent as a
  header, and never holds the key.
- Arguments are checked before any request and raise `InvalidArgumentError`: `customer_email` contains `@` and no spaces;
  `amount` is a finite `Decimal` greater than zero with at most two decimal places (floats are rejected; the server keeps
  cents, so a third decimal is refused with a message to round to cents first); `currency` is not empty; `billing_interval` is a `BillingInterval` or its string value;
  `merchant_subscription_ref` is 1 to 128 characters; the three URLs are http or https with a host. The rest is left to the
  server. `amount` is sent as a plain decimal string (`990.00`, `1000` for `Decimal("1E+3")`), never with an exponent.
- The `reason` of `refund_session` is 3 to 255 characters (`REFUND_REASON_MIN_LENGTH` and `REFUND_REASON_MAX_LENGTH`, exported by
  `polako.sdk`).
- `idempotency_key` is a `UUID` (sent as its text) or a string. A blank one, one of another type, one that is not printable
  ASCII (a tab inside is fine) or one with whitespace at either end raises `InvalidHeaderValueError`; the message names the
  argument, never the value.
- The HTTP client checks every header before it sends: the name is a non-empty token of ASCII letters, digits and
  ``!#$%&'*+-.^_`|~``, the value is text or ASCII
  bytes, printable (a tab inside is fine), without whitespace at either end. A bad name is an `InvalidArgumentError`, a bad
  value an `InvalidHeaderValueError`; the message names the header, never the value.
- `SubscriptionCreated` is immutable. The client keeps the API key private and hides it in `repr`.
- An answer to a subscription request that lacks the subscription ID or the registration form, or holds a value of the
  wrong kind, is an `HttpRequestError` whose cause is the reason; no result is built from half an answer.

### Webhooks

- A webhook is verified before it is read: the signature is checked over the raw body exactly as received, with
  `hmac.compare_digest`, and only then is the body decoded (UTF-8 JSON object). A forged body is a `WebhookSignatureError`
  whatever it contains (never an `AssertionError`). A body that was parsed and serialized again does not match.
- The registration-failure notification and the lifecycle events are told apart in both directions: a body with an `event`
  field is not a registration failure (`parse_registration_failed` rejects it and points to `parse_subscription_webhook`);
  a body with `success` and no `event` is not a lifecycle event (the lifecycle parser rejects it and points to
  `parse_registration_failed`). In a registration failure `success` must be `0` or `false` (missing or `null` is accepted).
- A signature that is present on a registration failure is always checked, whatever `allow_unsigned` says. A missing or blank
  one is rejected unless `allow_unsigned=True`; then the result has `signature_verified=False` and is otherwise read exactly
  like a signed one. `allow_unsigned` is keyword-only; an empty `api_key` is a `ConfigurationError` in every mode.
- An unknown event name is returned as `UnknownSubscriptionEvent`, not raised; unknown fields of a known event are ignored.
- A time is read the same way in webhooks and in management results: ISO 8601 with a trailing `Z`, a numeric offset
  (`+02:00`, `+0200`, `+02`) or none (then UTC), any number of fraction digits (kept to the microsecond, the rest cut off),
  seconds optional (`10:20`), only the digits 0-9. The result is always timezone-aware. A date with no time of day is
  refused. The `timestamp` of a payment callback of schema 1.1 is read the same way; that of the legacy format has no zone
  and stays naive.

### Registration page

- `render_registration_form` follows the card processor's naming, not the gateway's. A `FormPost` becomes a POST form with
  nine hidden inputs `Version`, `MerchantID`, `TerminalID`, `TotalAmount`, `Currency`, `Locale`, `PurchaseTime`, `OrderID`,
  `Signature` (an empty version is sent as `1`); an `HppFormPost` passes the provider's fields through in order; a
  `RedirectForm` is a link plus a `refresh` redirect when `auto_submit` is on, never a form and never an `<iframe>`.
- With `auto_submit` on, a posted form submits itself with one constant script (it calls the form element's own submit
  method, so a provider field named `submit` or `action` cannot shadow it) and always shows a visible button (not inside
  `<noscript>`); with it off the page has the same button and no script.
- The helper refuses what could be turned against the customer: the address must be an http or https URL with a host and no
  whitespace or control characters (`InvalidArgumentError`); every name, value and address is HTML-escaped; the script holds
  no data from the form; the page loads nothing from elsewhere; anything that is not a registration form is a `TypeError`.
  The input names for `FormPost` come from the gateway's reference page; confirm them on staging before production.

### Retries

- Only requests carrying an `Idempotency-Key` are retried, at most three attempts, with the same key and body. Payment
  methods and management methods are never retried.
- Retried statuses: 429, 500, 502, 503, 504. Never retried: 501, 505, 4xx other than 429, an unsupported address.
- Retried failures: timeouts; `httpx` network and protocol errors, including a stream that broke or ended; a connection that
  was reset, aborted, refused or broken, and an operating-system timeout; a stream that `anyio` reports as cut
  (`EndOfStream`, `BrokenResourceError`) where `httpcore` does not map it.
- TLS errors are told apart by where they happen and by the `reason` code, never by the text. A TLS error behind an
  `httpx.ConnectError` happened while connecting; one that reaches the SDK unwrapped comes from an established connection.
  It is looked for on the chain of the error: the `__cause__`, or the `__context__` when `raise ... from None` suppressed
  it; a context that was not suppressed (an error the caller was handling) is never followed, and the walk stops at an
  error of the SDK.
  - while connecting only a cut connection is retried (`ssl.SSLEOFError`, `ssl.SSLZeroReturnError`, `ssl.SSLSyscallError`,
    the reason `UNEXPECTED_EOF_WHILE_READING`, on a plain `SSLError` too, in both places); every other failure of the handshake is a fault of the setup that a repeat
    does not cure (`PACKET_LENGTH_TOO_LONG` and `BAD_LENGTH` too: while connecting they mean a peer or proxy that answers in plain text);
  - on an established connection a cut connection and a damaged record are retried: `DECRYPTION_FAILED_OR_BAD_RECORD_MAC`,
    `DECRYPTION_FAILED`, `BAD_RECORD_MAC`, `SSLV3_ALERT_BAD_RECORD_MAC`, `RECORD_LAYER_FAILURE`, `UNEXPECTED_RECORD`,
    `BAD_LENGTH`, `PACKET_LENGTH_TOO_LONG`, `APPLICATION_DATA_AFTER_CLOSE_NOTIFY`;
  - any other TLS error, and one whose code the running Python does not know, is raised at once. The handshake alerts
    `SSLV3_ALERT_UNEXPECTED_MESSAGE` and `TLSV1_ALERT_DECODE_ERROR` and `TLSV1_ALERT_INTERNAL_ERROR` are not retried: they are
    deterministic rejections (under TLS 1.3 they arrive unwrapped on the first read; a server sends the internal error for a lasting configuration problem).
- Never retried because a repeat gives the same result and spends the rate limit: a certificate that does not verify, a wrong
  protocol version, a failure to set up the client, `FileNotFoundError`, `PermissionError`.
- Every attempt counts against the endpoint's limit of 20 requests per 60 seconds. There is no overall deadline. After a
  network error or a timeout the wait is 0.5 s, then 1 s; after an HTTP 429 or 5xx with a `Retry-After` header the client
  waits as long as the server asks, up to 8 s. Three answers of 503 end in about 1.5 s; three answers of 429 with
  `Retry-After: 8` in about 16 s plus the attempts; three attempts that each run into the 30 s timeout take about 91.5 s and
  more (the timeout applies to each phase of an attempt). A merchant's own deadline should be well above a minute and a half.
  A read timeout is retried because the server replays a request with a key it has already seen.

### Error messages

- A failure before an answer arrived is an `HttpClientError` with the message `Request failed: <class>[: <text>]`; the
  original error is the `__cause__`. A timeout or a reset connection has no text, so the class names the failure; for an
  `httpx` error with no text the text of the innermost `OSError` on its chain is used. The chain is `__cause__`, or
  `__context__` when `raise ... from None` suppressed it; an error the caller was handling is not followed, and the walk
  stops at an error of the SDK. Any other unexpected failure is `Unexpected error during request: <class>[: <text>]`, with no
  search of the chain.
- After more than one attempt the message of a failure or of an error answer ends with
  `(after N attempts; the message is about the last one)`. An error answer with an empty body has no colon at the end.

### Client lifecycle

- The SDK is checked on asyncio only (retries wait with `asyncio.sleep`, the close uses asyncio tasks; where no asyncio loop runs, the close is a plain `aclose()` whose failure is logged). The client is set up once, before the first attempt: at `async with`, or at the start of a call outside it. A failure to
  set it up is an `HttpClientError` `Client set-up failed: <class>[: <text>]`, never retried, for errors of the environment
  (`OSError`, `ImportError` for a SOCKS proxy without `socksio`, `ValueError` for an unknown proxy scheme,
  `httpx.InvalidURL` for a malformed proxy URL or port). Any other error at set-up is a mistake in the code or a change in
  `httpx` and is raised as it is. Which failures occur depends on the `httpx` version: before 0.28 a missing `SSL_CERT_FILE`
  is skipped, a bad `SSL_CERT_DIR` fails at the call, and only an existing but malformed file fails at set-up; from 0.28 a
  missing file fails at set-up too. The package declares
  `httpx >= 0.25, < 1.0` and `anyio >= 3`.
- The close is the same at every exit (a call, `async with`) and runs as a task that the SDK keeps on the client object. A
  call closes the client it built for itself (decided before the build). The shared client of `async with` is closed by the last user: the last
  exit, or a call that borrowed it and outlives the exits, so one task's exit never closes the client under another task's
  call. Entering `async with` again (nested, or from another task) shares the open client and counts the entries; calls made
  outside `async with` while a client is open borrow it and are counted too.
- Leaving `async with` more often than entering it (a shutdown hook that runs twice, a client never entered) does nothing but
  emit a `RuntimeWarning`, attributed to the merchant's code, and will be a `RuntimeError` from 0.3.0. If the merchant's
  filters turn warnings into errors it is raised when nothing is propagating or being handled, and logged instead when an
  error is propagating or being handled (read from `sys.exc_info()` too, whatever the hook passes: a hand-written `__aexit__(None, None, None)` and an error handled by the synchronous code around the loop count), so as not to replace it.
- The close is bounded to 10 seconds (`CLOSE_TIMEOUT`, private, not a setting). A call that closes its own client can take
  that long to return if the close is unexpectedly slow; the real transport closes without a round trip with the peer (checked on httpcore 1.0.9 only, not on the 0.18 of the oldest floor), so
  this is an upper bound for a stalled peer, a starved event loop or a custom transport.
- No failure of the close comes out of a call or of `__aexit__`; it never replaces the outcome of a call or an error that is
  propagating. Every one is logged at warning level by `polako.sdk._async_client`:
  - `Closing the HTTP client failed: ...`, with the traceback, also when it comes after the SDK gave up waiting;
  - `... timed out after N seconds and was cancelled; its connections may stay open if it does not end`;
  - `... was cancelled before it ended; its connections may stay open`: the task that closes was cancelled while closing;
  - `... was cancelled before it started; no close was attempted, the client stays open`: `aclose` was never called;
  - `... ended cancelled although the SDK did not cancel it; its connections may stay open`: `aclose` ended cancelled by
    someone else;
  - `... is still running N seconds after it was cancelled; the SDK stops holding it`.
- "Never called" means the body of the coroutine that calls `aclose` never ran (the flag is set there, not when its task is created). It happens when the close task is cancelled
  before its first step; when the close task and the task that runs `aclose` are both cancelled after the first step and
  before `aclose` was called, in either order (what `asyncio.run` does at its end); and when the task that runs `aclose` is cancelled alone
  before it was called, which the waiting task logs (then the foreign-cancel line is not logged, since it says `aclose` was called). A close task
  cancelled alone after its first step is not such a case: `aclose` is called and then cancelled, and the close counts as
  interrupted. These are the usual ways, not an exhaustive list: the condition decides (for example, the task that runs
  `aclose` cancelled alone and then the close task, before it wakes, is logged by the close task's callback as never
  attempted).
- One cancellation is logged once, whatever the order in which asyncio steps the tasks: the SDK's own cancellation of `aclose`
  is never logged as a foreign one (that line is logged by the waiting task, after its wait returned). If the waiting task
  is cancelled after a foreign cancellation of `aclose` and before it wakes, only "cancelled before it ended" is logged, though `aclose` had already ended.
- When the SDK gives up waiting (the deadline, or the cancellation of the waiting task) it cancels `aclose` and holds its
  task for 10 more seconds (`CLOSE_HOLD`), because asyncio keeps only weak references to tasks (the `aclose` task is kept for its whole run too); the hold ends as soon as
  `aclose` does. If `aclose` is still running then, the SDK logs that and stops holding it, and asyncio may report it as `Task was destroyed but it is pending`.
- A caller cancelled while it waits for the close leaves at once with its cancellation; the close goes on in the background.
  A cancellation of the close task alone does not reach a caller that was not cancelled, but a caller cancelled in the same
  moment still gets its cancellation, on every supported Python. If the event loop shuts down before
  the close ends, the connections may stay open: a close cancelled when the loop cancels its tasks is logged, and a loop closed
  without cancelling them only gets asyncio's own message.
  A `TimeoutError` raised by `aclose` itself is a failure of the close, never the deadline.

### Management

- The management methods need `company_id` and `api_key` like `create_subscription`, with the key in the `company_api_key`
  header and nothing else signed. Arguments raise `InvalidArgumentError`: `subscription_id` is a `UUID` or a string that is
  one; `limit` is 1 to 100; `offset` is not negative; `sort_by` is one of `created_at`, `next_charge_at`,
  `last_charged_at`, `amount`, `status`; `sort_order` is `asc` or `desc`; `search` is not blank when given; `status` and
  `billing_interval` hold members of the enums or their string values (several match any of them; an empty collection is
  refused); `created_from` and `created_to` are a `date` or a timezone-aware `datetime` (a naive one is rejected), sent as
  ISO 8601 (a `date` as a plain day, a `datetime` in UTC to the second), both bounds inclusive. `search` is matched by the server against the customer's email, the merchant
  reference and the id.
- HTTP 400 stays a plain `HttpRequestError` (the server answers it for a filter or sort field it does not accept).
- Results are read tolerantly: an unknown value of a known enum field stays the raw string and unknown fields are ignored; a
  missing field or one of the wrong type is an `HttpRequestError` whose cause is the decoding error. Money is a `Decimal`
  whether the server sends a string or a number; times are timezone-aware; `charge_date` is a `date`.
- `pause_subscription`, `resume_subscription` and `cancel_subscription` answer nothing on success. A status that does not
  allow the change (pause needs `active`, resume needs `paused`, a cancelled subscription accepts nothing) and subscriptions
  switched off for the company are both a `ConflictError`; the server's message says which. After a network error the
  change may or may not have been applied: read the subscription with `get_subscription` before repeating it.

## Decisions

| Name | Decision | State (implemented: the code follows it; decided: agreed, nothing to build) |
|------|----------|-------|
| result-with-key | `create_subscription` returns a result object carrying the used idempotency key; the caller may pass their own key (recommended) | implemented |
| client-config | `company_id` and the API key are client constructor parameters; the API key is the same value as `secret_key`; the header keeps the name `company_api_key` (the platform's proxy accepts underscores) | implemented |
| unsigned-registration | A registration failure without a signature is rejected unless `allow_unsigned=True` | implemented |
| currency-checked-by-server | `currency` is a plain string validated by the server (the gateway knows RSD, RUB, EUR, USD and applies a platform-wide allow-list that answers 422) | implemented |
| unknown-event | An unknown webhook event is returned as `UnknownSubscriptionEvent` instead of raising | implemented |
| retry-502 | 502 is retried together with 429, 500, 503 and 504, keyed requests only, at most three attempts; 501, 505 and the other statuses are not | implemented |
| redirect-form | The wire type `iframe` is a redirect target, so the SDK names the model `RedirectForm` and the helper renders a redirect, not an `<iframe>`; the wire value `iframe` is still accepted. Nothing in the API says the page is embeddable, and hosted payment pages commonly refuse framing | implemented |
| management-by-api-key | Merchants manage subscriptions with the platform API key as well as from the dashboard. One route per operation serves both: a dashboard login is used when the request carries one, otherwise the API key, and a login wins over a key sent beside it | implemented; the server release is pending |
| no-standalone-verify | The signature check is not a public function: the two parsers already verify, and a second entry point would invite reading the body without the checks. A merchant who queues webhooks passes the raw body and the `X-Signature` value to the worker and calls the parser there. Revisit if a real need appears, under a name that cannot be mistaken for the payment callback check | decided |
| management-no-retry | Management methods are never retried, neither the changes nor the reads. The server takes no `Idempotency-Key` on pause, resume and cancel, and a repeat after a lost response would meet the new status and answer 409, which cannot be told from a real refusal. The caller reads the subscription and decides. Reads could be retried safely, but the retry rules are shared with the payment methods. Revisit when the server accepts an `Idempotency-Key` on the changes | implemented |
| management-not-found | A 404 is a `NotFoundError`, a subclass of `HttpRequestError`, so that "no such subscription" is not caught with every other HTTP failure | implemented |
| management-one-page | `list_subscriptions` returns one page (`limit`, `offset`) as a `SubscriptionPage`; there is no iterator, and one can be added later without changing it | implemented |
| tolerant-reading | Management results keep an unknown enum value as the raw string and ignore unknown fields, so that a status added by the server does not break a merchant's listing | implemented |

## Subscription management on the server

The same routes serve the dashboard and the platform API key: `GET /v1/company/{company_id}/subscriptions` (list), `GET
.../{subscription_id}` (detail), and `PATCH .../{subscription_id}/pause`, `/resume`, `/cancel` (status 204). A request that
carries the dashboard's login is a dashboard call; one without it must carry `company_api_key` of the company in the path.
In the released server these operations need a dashboard session; the routes that accept the key are built and wait for a
release.

For an API key the server answers 401 for a missing or unknown key, 403 for the key or the subscription of another company,
404 for an unknown subscription, 409 when subscriptions are switched off for the company or the status does not allow the
change, 422 for a malformed identifier. Reading is allowed even when subscriptions are switched off. A key has full
authority over its company's subscriptions.

The detail carries the charge history and the event journal, so there is no separate route for the payments of a
subscription. Cancelling does not refund; a refund goes through the payment refund, and the `payment_session_id` of a
charge in the history is what `refund_session` needs.

## Open questions

- Whether test and production use separate platforms and keys.

## Notes from the dashboard

- A merchant finds their `company_id` on the Company info page of the dashboard, read-only and copyable, at the right edge
  of the header strip with the company name, PIB and MB. The README and the examples say so.
- Subscriptions are switched on for a company by Polako, not by the merchant; until then `create_subscription` raises
  `ConflictError`. The README says so.

## Change log

| Date | Change |
|------|--------|
| 2026-10-08 | Created from the gateway contract: create, registration forms and their rendering, webhook parsers, exceptions by status, retries for keyed requests, client-side argument checks |
| 2026-10-09 | Management methods and their models; `NotFoundError`; one reader for times (always timezone-aware); retries limited to the statuses and failures above; read timeouts retried |
| 2026-10-21 | v0.43 (SDK 0.2.1): typed argument errors (`InvalidArgumentError`, `InvalidHeaderValueError`); checks of the API key and of headers; messages of network failures; classification of TLS failures in retries; client set-up, closing and `async with` rules; limits of the refund reason; the text regrouped by topic |
