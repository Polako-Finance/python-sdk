# Polako Finance Python SDK

[![PyPI version](https://badge.fury.io/py/polako-finance.svg)](https://badge.fury.io/py/polako-finance)
[![Python Support](https://img.shields.io/pypi/pyversions/polako-finance.svg)](https://pypi.org/project/polako-finance/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Official Python SDK for the Polako Finance payment gateway. This library provides an **async-first** interface following modern Python best practices for seamless integration with the Polako Finance API.

The SDK uses the `polako.sdk` namespace to avoid naming conflicts with other packages.

## Features

- ✅ **Async-First** - Built with async/await for optimal performance
- ✅ **Type Safety** - Full type hints for better IDE support and code quality
- ✅ **Easy to Use** - Simple, intuitive API design
- ✅ **Comprehensive** - Complete coverage of Polako Finance payment gateway features
- ✅ **Well Documented** - Extensive documentation and examples
- ✅ **Production Ready** - Robust error handling and validation
- ✅ **Modern** - Follows current Python async best practices

## Installation

Install using pip:

```bash
pip install polako-finance
```

Or using poetry:

```bash
poetry add polako-finance
```

## Requirements

- Python 3.10+
- httpx >= 0.25

## Quick Start

```python
import asyncio
from polako.sdk import PolakoClient, OrderDetails, OrderItem, CustomerInfo, CustomerAddress
from decimal import Decimal
from uuid import UUID

async def create_payment():
    # Use as context manager for automatic cleanup
    async with PolakoClient(test_env=True) as client:
        # Create order details
        order = OrderDetails(
            currency="RSD",
            language="en",
            order_id="ORDER-123",
            items=[
                OrderItem(
                    code="PROD-001",
                    name="Premium Product",
                    description="A premium product",
                    price=Decimal("100.00"),
                    quantity=2,
                    tax="VAT"
                )
            ],
            total=Decimal("200.00")
        )
        
        # Create customer information
        customer = CustomerInfo(
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            phone="+381123456789",
            address=CustomerAddress(
                address="Knez Mihailova 5",
                city="Belgrade",
                state="Central Serbia",
                zip="11000",
                country="RS"
            )
        )
        
        # Create payment session
        session = await client.create_order(
            order=order,
            customer=customer,
            platform_id=UUID("00000000-0000-0000-0000-000000000000"),  # your platform ID
            secret_key="your-secret-key"
        )
        
        print(f"Payment URL: {session.paymentPageUrl}")
        print(f"Session ID: {session.paymentSessionId}")
        print(f"Expires at: {session.expiresAt}")
        
        return session

# Run async function
if __name__ == "__main__":
    session = asyncio.run(create_payment())
```

## Payment Callback Handling

Handle payment callbacks from the gateway:

Always pass `secret_key` in production: if it is omitted, the signature is **not** verified. A callback with a wrong
signature raises `AssertionError`.

```python
from polako.sdk import PolakoClient

# Parse callback payload
callback_payload = request.body  # Raw body from your webhook endpoint
try:
    callback = PolakoClient.parse_payment_callback(
        payload=callback_payload,
        secret_key="your-secret-key"  # Verifies the signature
    )
except AssertionError:
    ...  # Signature mismatch: reject the request (e.g. respond with HTTP 400)

if callback.success:
    print(f"Payment successful for order: {callback.order_id}")
    print(f"Transaction ID: {callback.tx_id}")
    print(f"Amount: {callback.total} {callback.currency}")
else:
    print(f"Payment failed for order: {callback.order_id}")

# Merchant info is included in the callback (v0.1.9+)
if callback.merchant:
    print(f"Merchant: {callback.merchant.name}")
    print(f"PIB: {callback.merchant.pib}")
    print(f"Address: {callback.merchant.address}")
```

## Subscriptions

A subscription charges a customer's card on a schedule. You create it, the customer goes through a one-time card
registration (3DS), and from then on the gateway charges the card every billing interval and tells your server about
every charge.

You need:

- the **company ID**, shown on the Company info page of the dashboard, and the **API key** of your platform (the same API
  key that signs payments);
- subscriptions switched on for your company: Polako does that, and until it is done `create_subscription` raises a
  `ConflictError`;
- a **webhook URL** for your platform, set in the platform settings in the dashboard: charge notifications are sent there;
- an **error URL**, which you give for every subscription: a failed card registration is reported there.

### Create a subscription and send the customer to the card registration

```python
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from polako.sdk import BillingInterval, PolakoClient, render_registration_form

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000000")  # your company ID
API_KEY = "your-secret-key"  # the API key of your platform

app = FastAPI()


@app.post("/subscribe")
async def subscribe():
    key = str(uuid4())  # keep it with your order before the call: repeating a request with the same key is safe
    async with PolakoClient(test_env=True, company_id=COMPANY_ID, api_key=API_KEY) as client:
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
    return HTMLResponse(render_registration_form(created.registration_form))
```

- `create_subscription` returns a `SubscriptionCreated` with the `subscription_id`, the `registration_form` and the
  `idempotency_key` that was used (a key is generated if you do not pass one).
- The subscription becomes active only after the customer completes the registration. A failure is reported to your
  error URL; every later charge is reported to your webhook URL.
- Repeating a request with the same `idempotency_key` returns the same subscription. A request that fails on the
  network (a timeout included), or with HTTP 429, 500, 502, 503 or 504, is repeated for you, up to three attempts, with the
  same key. There is no overall deadline: with the default 30 second timeout a call that keeps failing can take about
  100 seconds before it raises.
- The endpoint accepts 20 requests per 60 seconds, and every attempt counts. Beyond that you get a `RateLimitedError` with
  `retry_after` set.
- `amount` has at most two decimal places (`990.00`): the gateway keeps cents, so a third decimal is refused with a `ValueError`
  instead of being rounded; round the amount to cents yourself first.
- `merchant_subscription_ref` is your own reference to the plan or product (1 to 128 characters). A customer can have
  one live subscription per reference; a second one is a `ConflictError`.
- `render_registration_form` returns a complete HTML page: a form that posts the customer to the card processor, or a
  redirect, depending on the processor. Return it as an HTML response. It sends the customer on at once with one small
  script and always shows a "Continue" button as well, for a browser or a page policy that blocks the script. Pass
  `auto_submit=False` if your site forbids inline scripts: the page then holds no script and the customer presses the button.

### Read the webhooks

```python
from fastapi import HTTPException, Request
from polako.sdk import (
    ChargeFailed,
    ChargeSucceeded,
    DroppedExternally,
    SubscriptionCancelled,
    WebhookPayloadError,
    WebhookSignatureError,
    parse_subscription_webhook,
)


@app.post("/polako/subscription-webhook")
async def subscription_webhook(request: Request):
    try:
        event = parse_subscription_webhook(await request.body(), request.headers.get("X-Signature"), API_KEY)
    except WebhookSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    except WebhookPayloadError:
        raise HTTPException(status_code=422, detail="invalid payload")

    if isinstance(event, ChargeSucceeded):
        print(f"Charged {event.amount} {event.currency} for {event.merchant_subscription_ref}")
    elif isinstance(event, ChargeFailed):
        print(f"Charge failed for {event.merchant_subscription_ref}: {event.error_class}")
    elif isinstance(event, DroppedExternally):
        print(f"The card of {event.merchant_subscription_ref} was revoked")
    elif isinstance(event, SubscriptionCancelled):
        print(f"{event.merchant_subscription_ref} was cancelled")
    return {"status": "ok"}
```

| Event | Meaning | Fields besides `subscription_id` and `merchant_subscription_ref` |
|-------|---------|------------------------------------------------------------------|
| `ChargeSucceeded` | A scheduled charge went through | `amount` (`Decimal`), `currency`, `charged_at` |
| `ChargeFailed` | A charge failed | `error_class` |
| `DroppedExternally` | The card agreement was revoked by the card provider | none |
| `SubscriptionCancelled` | The subscription was cancelled | none |
| `UnknownSubscriptionEvent` | A kind of event this version of the SDK does not know | `event` (its name), `data` (the whole payload) |

**Pass the body exactly as you received it.** The signature is checked over the raw bytes, so JSON that your framework
has parsed and serialized again no longer matches and is rejected. Use the raw body (`await request.body()` above).

Answer with a 2xx status. A server error or no answer makes the gateway try again, up to three attempts; any other
error status is final.

### Read the registration failure

When the card registration fails, the gateway sends a notification to the error URL you gave. It has no `event` field,
so it is read with its own function.

```python
from polako.sdk import parse_registration_failed


@app.post("/polako/subscription-error")
async def subscription_error(request: Request):
    try:
        failure = parse_registration_failed(await request.body(), request.headers.get("X-Signature"), API_KEY)
    except WebhookSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    print(f"Registration of {failure.merchant_subscription_ref} failed: {failure.error_message}")
    return {"status": "ok"}
```

`parse_registration_failed` and `parse_subscription_webhook` each refuse the other's body and tell you which function to
use, so a mixed-up URL is easy to spot. A notification without a signature is rejected. Subscriptions made without a
platform are notified unsigned; pass `allow_unsigned=True` to accept those, and check `failure.signature_verified`:
it is `False` for them, because anyone who knows your URL could send such a notification.

### Errors

| Exception | HTTP status | Meaning |
|-----------|-------------|---------|
| `UnauthorizedError` | 401 | The API key is missing or unknown |
| `ForbiddenError` | 403 | The API key belongs to another company, or the subscription does |
| `NotFoundError` | 404 | There is no such subscription |
| `ConflictError` | 409 | Subscriptions are switched off for your company, the customer already has a live subscription with this reference, or the status does not allow the change (resuming an active subscription, say) |
| `RequestValidationError` | 422 | A field was rejected, for example a currency that is not allowed |
| `RateLimitedError` | 429 | Too many requests; `retry_after` is the number of seconds to wait |
| `ServerError` | 5xx | The gateway or the card processor failed |

All of them are `HttpRequestError`s, so `except HttpRequestError` still catches every one. A network error is an
`HttpClientError`. A client without `company_id` or `api_key` raises `ConfigurationError` before sending anything, and an
invalid argument is a `ValueError` before any request.

### Managing a subscription

Read and manage the subscriptions of your company with the same client and API key you create them with. The SDK sends
each of these calls once and does not repeat it, see "A change that did not get an answer" below.

```python
from uuid import UUID

from polako.sdk import PolakoClient, SubscriptionStatus

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000000")  # your company ID
API_KEY = "your-secret-key"  # the API key of your platform


async def show_active_subscriptions():
    async with PolakoClient(test_env=True, company_id=COMPANY_ID, api_key=API_KEY) as client:
        page = await client.list_subscriptions(status=SubscriptionStatus.ACTIVE, limit=20)
        print(f"{page.total} active, showing {len(page.items)}")
        for subscription in page.items:
            print(subscription.id, subscription.customer_email, subscription.amount, subscription.next_charge_at)

        if page.items:
            details = await client.get_subscription(page.items[0].id)
            print(details.status, details.saved_card.masked_pan if details.saved_card else "no card")
            for charge in details.charge_history:
                print(charge.charge_date, charge.status, charge.amount, charge.payment_session_id)
```

- `list_subscriptions` returns a `SubscriptionPage`: `items` (a tuple of `SubscriptionSummary`), `total` (how many match in
  all), `limit` (the page size) and `offset`. It takes these arguments, all optional and all by keyword:

  | Argument | Meaning |
  |----------|---------|
  | `status` | One `SubscriptionStatus` (or its text), or several; a subscription matches any of them |
  | `billing_interval` | One `BillingInterval` (or its text), or several |
  | `search` | Text looked for in the customer's email, in your `merchant_subscription_ref` and in the subscription ID, ignoring case |
  | `created_from`, `created_to` | A `date` (the whole day) or a `datetime` with a timezone (to the second); both ends are included |
  | `sort_by`, `sort_order` | `created_at` (the default), `next_charge_at`, `last_charged_at`, `amount` or `status`; `asc` or `desc` (the default, newest first) |
  | `limit`, `offset` | 1 to 100 subscriptions per page (10 by default); how many matching subscriptions to skip |

- `get_subscription` returns a `SubscriptionDetails`: the customer, the card (only its masked number, brand and expiry,
  never the card data itself), `next_charge_at` and `last_charged_at`, `charge_history` (newest first, each charge with its
  `status`, `amount` and the `payment_session_id` you pass to `refund_session` to return it) and `events` (the journal,
  oldest first). The ID is a `UUID` or a string holding one.
- Reading works even when subscriptions are switched off for your company.
- A time is a timezone-aware `datetime`, an amount a `Decimal`. A status the SDK does not know yet is returned as its text
  instead of a `SubscriptionStatus`.

To read every subscription, ask for the next page until you have them all:

```python
async def read_all_subscriptions(client):
    subscriptions = []
    while True:
        page = await client.list_subscriptions(limit=100, offset=len(subscriptions))
        subscriptions.extend(page.items)
        if not page.items or len(subscriptions) >= page.total:
            return subscriptions
```

A subscription is in one of these statuses (`SubscriptionStatus`):

| Status | Meaning |
|--------|---------|
| `pending_registration` | The customer has not finished the card registration yet |
| `registration_failed` | The card registration failed; the subscription is over |
| `active` | Charged on schedule |
| `past_due` | The last charge failed and is being retried |
| `paused` | Suspended; nothing is charged |
| `cancelled` | Over; nothing more is charged |

Three calls change a subscription. Each returns nothing when it worked:

| Call | Works when the subscription is | Then |
|------|-------------------------------|------|
| `pause_subscription(subscription_id)` | `active` | `paused`: no charges until you resume it; the next charge date is kept |
| `resume_subscription(subscription_id)` | `paused` | `active` again; a charge that came due during the pause is attempted soon after |
| `cancel_subscription(subscription_id)` | `active`, `paused` or `past_due` | `cancelled` for good, and your webhook receives `SubscriptionCancelled`; the card is released unless another live subscription uses it |

Cancelling does not return money that was already charged: refund a charge with `refund_session`, using the
`payment_session_id` from the charge history.

```python
from polako.sdk import ConflictError, HttpClientError, HttpRequestError, NotFoundError, PolakoClient


async def pause_subscription_of(subscription_id):
    async with PolakoClient(test_env=True, company_id=COMPANY_ID, api_key=API_KEY) as client:
        try:
            await client.pause_subscription(subscription_id)
        except NotFoundError:
            print("There is no such subscription")
        except ConflictError as error:
            # Not active (already paused or cancelled, say), or subscriptions are switched off for your company.
            print(f"It cannot be paused: {error.response_body}")
        except HttpRequestError as error:
            print(f"The gateway refused: status {error.status_code}")
        except HttpClientError:
            # The request may or may not have arrived. Look before you try again.
            details = await client.get_subscription(subscription_id)
            print(f"The subscription is {details.status}")
```

**A change that did not get an answer.** If the network fails while a change is on its way, the SDK raises
`HttpClientError` and cannot tell whether the change was made. It does not repeat the call, because the repeat would find
the subscription already changed and be refused with a `ConflictError`, which looks the same as a real refusal. Read the
subscription with `get_subscription` and repeat the change only if it did not happen.

## Configuration

### Client Options

```python
from polako.sdk import PolakoClient

# Initialize client with options
async with PolakoClient(
    timeout=30.0,      # Request timeout in seconds (default: 30.0)
    test_env=False     # Use production environment (default: False)
) as client:
    # Your code here
    pass
```

### Supported Currencies

- `RSD` - Serbian Dinar

### Supported Languages

- `sr` - Serbian
- `en` - English
- `ru` - Russian

### Tax Schemas

- `VAT` - Value Added Tax
- `No_VAT` - No VAT
- `Reduced_VAT` - Reduced VAT rate

## Error Handling

The SDK provides specific exceptions for different error scenarios:

```python
from polako.sdk import PolakoClient, HttpClientError, HttpRequestError

try:
    async with PolakoClient() as client:
        session = await client.create_order(order, customer, platform_id, secret_key)
except ValueError as e:
    # Validation error (invalid order or customer data)
    print(f"Validation error: {e}")
except HttpRequestError as e:
    # HTTP request failed (4xx or 5xx response)
    print(f"Request failed with status {e.status_code}: {e.message}")
    print(f"Response: {e.response_body}")
except HttpClientError as e:
    # Network error or other client-side issue
    print(f"Client error: {e.message}")
except Exception as e:
    # Unexpected error
    print(f"Unexpected error: {e}")
```

Beyond `HttpRequestError`, the SDK raises a class of its own for the statuses you will want to handle separately:
`UnauthorizedError` (401), `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409), `RequestValidationError` (422),
`RateLimitedError` (429, with `retry_after`) and `ServerError` (5xx). All of them are subclasses of `HttpRequestError`, so
the code above keeps working. See [Subscriptions](#subscriptions) for what they mean there.

## Advanced Usage

### Custom Customer Address

```python
from polako.sdk import CustomerInfo, CustomerAddress

customer = CustomerInfo(
    first_name="John",
    last_name="Doe",
    email="john.doe@example.com",
    phone="+381123456789",
    address=CustomerAddress(
        address="123 Main Street",
        city="Belgrade",
        state="Central Serbia",
        zip="11000",
        country="RS"
    )
)
```

### Multiple Items in Order

```python
from polako.sdk import OrderDetails, OrderItem
from decimal import Decimal

order = OrderDetails(
    currency="RSD",
    language="en",
    order_id="ORDER-789",
    items=[
        OrderItem(
            code="ITEM-001",
            name="Product A",
            description="First product",
            price=Decimal("100.00"),
            quantity=2,
            tax="VAT"
        ),
        OrderItem(
            code="ITEM-002",
            name="Product B",
            description="Second product",
            price=Decimal("50.00"),
            quantity=1,
            tax="VAT"
        )
    ],
    total=Decimal("250.00")  # 100*2 + 50*1
)
```

## Development

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/Polako-Finance/python-sdk.git
cd python-sdk

# Install the SDK and its development tools using poetry
poetry install

# Install the tests (a separate project, see below)
poetry -C tests install

# Activate virtual environment
poetry shell
```

### Running Tests

The tests are a separate Poetry project in `tests/` with its own dependencies and lock file. They install the SDK from
the repository root in editable mode, and building the SDK never needs them. You can read them in the repository to see
how the SDK is used.

```bash
# Run all tests
poetry -C tests run pytest

# Run with coverage of the SDK package
poetry -C tests run pytest --cov=polako.sdk --cov-report=term

# Run a specific test file
poetry -C tests run pytest test_client.py
```

Most tests run against an in-process fake gateway. The tests in `tests/integration` run the whole subscription flow
against a local emulator of the gateway over real HTTP on free local ports, with a small merchant endpoint that reads
webhooks with the SDK. Nothing leaves your machine.

> The `Makefile` offers shortcuts for the commands in this section (`make test`, `make test-cov`, `make lint`,
> `make format`, `make type-check`, `make check`, `make check-docs`, `make docs-update`). They need GNU make
> (Linux, macOS, WSL); on Windows run the `poetry run ...` commands shown here.

### Code Quality

```bash
# Format code with black
poetry run black src/ tests/

# Sort imports with isort
poetry run isort src/ tests/

# Linting with flake8
poetry run flake8 src/ tests/

# Type checking with mypy
poetry run mypy src/
```

### Checking the Documentation

The Python code blocks in `README.md`, `README.pypi.md` and `examples/README.md` are checked against the SDK, so the
documentation cannot silently drift from the code. The check does not run the code: it verifies the syntax, the names
imported from `polako.sdk`, and that every call to an SDK class or client method matches its real signature.

```bash
# Run the check (also runs in CI as the `docs` job)
poetry run python scripts/check_docs.py
```

Every code block is pinned by a hash in `scripts/docs_manifest.json`. If you edit, add or remove a code block, the
check fails and names the block (`NEW BLOCK`, `CHANGED BLOCK` or `REMOVED BLOCK`). Review the change, then accept it:

```bash
poetry run python scripts/check_docs.py --update
```

The documentation is the source of truth: the check follows it, not the other way round. Write examples the way a
merchant would use the SDK; if the check disagrees, fix the SDK or `scripts/check_docs.py`, not the example.

### Pre-commit Hooks

```bash
# Install pre-commit hooks
poetry run pre-commit install

# Run manually
poetry run pre-commit run --all-files
```

## API Reference

### PolakoClient

Async client for Polako Finance API.

#### Methods

- `async create_order(order, customer, platform_id, secret_key)` - Create a new payment order
- `async get_session_details(session_id)` - Get details of a payment session
- `async get_payment_url(session_id, payment_option_id, customer, language_code, terms_accepted, address_shipping=None)` - Get a payment URL for an existing session
- `async check_order_status(session_id, platform_id, secret_key)` - Check the status of a payment session
- `async refund_session(session_id, platform_id, secret_key, reason, refund_items=None)` - Full or partial refund
- `parse_payment_callback(payload, secret_key)` - Parse payment callback (static method)
- `async create_subscription(*, customer_email, amount, currency, billing_interval, merchant_subscription_ref, success_url, cancel_url, error_url, idempotency_key=None)` - Create a subscription (the client needs `company_id` and `api_key`)
- `async list_subscriptions(*, status=None, billing_interval=None, search=None, created_from=None, created_to=None, sort_by=None, sort_order=None, limit=10, offset=0)` - One page of the subscriptions of your company
- `async get_subscription(subscription_id)` - One subscription with its customer, card, charge history and journal
- `async pause_subscription(subscription_id)`, `async resume_subscription(subscription_id)`, `async cancel_subscription(subscription_id)` - Change a subscription

#### Functions

- `parse_subscription_webhook(body, signature, api_key)` - Check and read a subscription webhook: `ChargeSucceeded`, `ChargeFailed`, `DroppedExternally`, `SubscriptionCancelled` or `UnknownSubscriptionEvent`
- `parse_registration_failed(body, signature, api_key, *, allow_unsigned=False)` - Check and read the notification about a failed card registration
- `render_registration_form(form, *, auto_submit=True)` - Turn a registration form into an HTML page for the customer

#### Context Manager

The client supports async context manager protocol for automatic resource cleanup:

```python
async with PolakoClient() as client:
    # Client automatically manages connection lifecycle
    session = await client.create_order(...)
# Resources are automatically cleaned up here
```

### Models

- `OrderDetails` - Order information
- `OrderItem` - Individual order item
- `CustomerInfo` - Customer information
- `CustomerAddress` - Customer address details
- `SessionInfo` - Payment session response
- `PaymentCallback` - Parsed payment callback data
- `MerchantInfo` - Merchant details from callbacks (name, PIB, address)
- `PaymentSessionDetails`, `PaymentOption`, `PaymentUrlResult`, `InitCustomerInfo` - Session details and payment URL
- `OrderStatusResponse`, `OrderStatusItem` - Result of `check_order_status`
- `RefundItem`, `RefundResponse`, `RefundedItem` - Refunds
- `SubscriptionCreated`, `BillingInterval` - Result and input of `create_subscription`
- `FormPost`, `HppFormPost`, `RedirectForm` - The three kinds of registration form
- `ChargeSucceeded`, `ChargeFailed`, `DroppedExternally`, `SubscriptionCancelled`, `UnknownSubscriptionEvent` - Subscription webhook events (type alias `SubscriptionWebhookEvent`)
- `RegistrationFailed` - A failed card registration
- `SubscriptionPage`, `SubscriptionSummary`, `SubscriptionDetails` - Result of `list_subscriptions` and `get_subscription`
- `SubscriptionCustomer`, `SavedCard`, `ChargeAttempt`, `SubscriptionEvent` - The parts of a `SubscriptionDetails`
- `SubscriptionStatus`, `ChargeAttemptStatus` - Status of a subscription and of one of its charges

## Support

- **Documentation**: [https://docs.polako-finance.com](https://docs.polako-finance.com)
- **Issues**: [GitHub Issues](https://github.com/Polako-Finance/python-sdk/issues)
- **Email**: support@polako-finance.com

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the release history.

---

Made with ❤️ by [Polako Finance](https://polako-finance.com)
