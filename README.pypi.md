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

- Python 3.9+
- httpx >= 0.25

## Quick Start

```python
import asyncio
from polako.sdk import PolakoClient, OrderDetails, OrderItem, CustomerInfo
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
            phone="+381123456789"
        )
        
        # Create payment session
        session = await client.create_order(
            order=order,
            customer=customer,
            platform_id=UUID("your-platform-id"),
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

```python
from polako.sdk import PolakoClient

# Parse callback payload
callback_payload = request.body  # From your webhook endpoint
callback = PolakoClient.parse_payment_callback(
    payload=callback_payload,
    secret_key="your-secret-key"  # Optional, for signature verification
)

if callback.success:
    print(f"Payment successful for order: {callback.order_id}")
    print(f"Amount: {callback.total} {callback.currency}")
else:
    print(f"Payment failed for order: {callback.order_id}")
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
            price=Decimal("50.00"),
            quantity=2,
            tax="VAT"
        ),
        OrderItem(
            code="ITEM-002",
            name="Product B",
            price=Decimal("75.00"),
            quantity=1,
            tax="VAT"
        ),
    ],
    total=Decimal("175.00")  # 50*2 + 75*1
)
```

## API Reference

### PolakoClient

Async client for Polako Finance API.

#### Methods

- `async create_order(order, customer, platform_id, secret_key)` - Create a new payment order
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

## Support

- **Documentation**: [https://docs.polako-finance.com](https://docs.polako-finance.com)
- **GitHub**: [https://github.com/Polako-Finance/python-sdk](https://github.com/Polako-Finance/python-sdk)
- **Issues**: [GitHub Issues](https://github.com/Polako-Finance/python-sdk/issues)
- **Email**: support@polako-finance.com

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/Polako-Finance/python-sdk/blob/main/LICENSE) file for details.
