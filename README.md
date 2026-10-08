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
                country="Serbia"
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
        country="Serbia"
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
