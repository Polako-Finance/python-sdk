# Polako Finance SDK Examples

This directory contains example scripts demonstrating how to use the Polako Finance Python SDK.

## Prerequisites

Before running these examples, make sure you have:

1. Installed the SDK:
   ```bash
   pip install polako-finance
   ```

2. Obtained your credentials from Polako Finance:
   - Platform ID (UUID)
   - Secret Key

## Examples

### 1. Basic Usage (`example.py`)

Demonstrates basic usage of the async client to create a payment session.

**Run:**
```bash
python example.py
```

**Key features:**
- Async/await syntax
- Context manager usage
- Creating order items
- Setting up customer information
- Creating a payment session
- Automatic resource cleanup
- Error handling

### 2. Payment Callback Handler (`callback_example.py`)

Demonstrates how to handle payment callbacks from the gateway.

**Run:**
```bash
python callback_example.py
```

**Key features:**
- Parsing callback payloads
- Signature verification
- Processing successful payments
- Handling failed payments

## Configuration

Before running the examples, update the following values:

```python
# Replace these with your actual credentials
PLATFORM_ID = UUID("your-platform-id-here")
SECRET_KEY = "your-secret-key-here"
```

## Testing

All examples use `test_env=True` by default, which points to the staging environment. For production:

```python
# Change this:
async with PolakoClient(test_env=True) as client:
    ...

# To this:
async with PolakoClient(test_env=False) as client:
    ...
```

## Integration with Web Frameworks

### FastAPI Example

```python
from fastapi import FastAPI, Request
from polako.sdk import PolakoClient, OrderDetails, OrderItem, CustomerInfo
from decimal import Decimal
from uuid import UUID

app = FastAPI()

@app.post('/create-payment')
async def create_payment(data: dict):
    async with PolakoClient(test_env=True) as client:
        order = OrderDetails(
            currency="RSD",
            language="en",
            order_id=data['order_id'],
            items=[OrderItem(**item) for item in data['items']],
            total=Decimal(data['total'])
        )
        
        customer = CustomerInfo(**data['customer'])
        
        session = await client.create_order(
            order=order,
            customer=customer,
            platform_id=UUID(app.config['PLATFORM_ID']),
            secret_key=app.config['SECRET_KEY']
        )
        
        return {
            'payment_url': session.paymentPageUrl,
            'session_id': session.paymentSessionId
        }

@app.post('/webhook')
async def webhook(request: Request):
    body = await request.body()
    callback = PolakoClient.parse_payment_callback(
        payload=body.decode('utf-8'),
        secret_key=app.config['SECRET_KEY']
    )
    
    if callback.success:
        # Process successful payment
        pass
    
    return {'status': 'ok'}
```

### Quart Example (Async Flask)

```python
from quart import Quart, request, jsonify
from polako.sdk import PolakoClient, OrderDetails, OrderItem, CustomerInfo
from decimal import Decimal
from uuid import UUID

app = Quart(__name__)

@app.route('/create-payment', methods=['POST'])
async def create_payment():
    data = await request.json
    
    async with PolakoClient(test_env=True) as client:
        order = OrderDetails(
            currency="RSD",
            language="en",
            order_id=data['order_id'],
            items=[OrderItem(**item) for item in data['items']],
            total=Decimal(data['total'])
        )
        
        customer = CustomerInfo(**data['customer'])
        
        session = await client.create_order(
            order=order,
            customer=customer,
            platform_id=UUID(app.config['PLATFORM_ID']),
            secret_key=app.config['SECRET_KEY']
        )
        
        return jsonify({
            'payment_url': session.paymentPageUrl,
            'session_id': session.paymentSessionId
        })

@app.route('/webhook', methods=['POST'])
async def webhook():
    body = await request.data
    callback = PolakoClient.parse_payment_callback(
        payload=body.decode('utf-8'),
        secret_key=app.config['SECRET_KEY']
    )
    
    if callback.success:
        # Process successful payment
        pass
    
    return '', 200
```

## Best Practices

1. **Always use signature verification** in production for webhooks
2. **Use environment variables** for credentials, never hardcode them
3. **Implement proper error handling** for all API calls
4. **Use context managers** (`async with`) for automatic resource cleanup
5. **Validate order totals** before creating payment sessions
6. **Log all payment events** for audit trails
7. **Use test environment** during development

## Support

For more information, see:
- [Main README](../README.md)
- [API Documentation](https://docs.polako-finance.com)
- [GitHub Issues](https://github.com/Polako-Finance/python-sdk/issues)
