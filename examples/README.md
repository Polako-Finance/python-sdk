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

### 3. Subscriptions (`subscription_example.py`)

A small merchant server (FastAPI) for the whole subscription flow: it creates a subscription, sends the customer to the
card registration, and reads the notifications the gateway sends afterwards (every charge, a revoked card, a cancellation
and a failed card registration).

**Run:**
```bash
pip install polako-finance fastapi uvicorn
uvicorn subscription_example:app --port 8000
curl -X POST "http://localhost:8000/subscribe?email=jane.smith@example.com"
```

The gateway has to reach the two notification URLs, so set `SHOP_URL` in the file to an address it can open (for example a
tunnel to your machine while you try this out), and put your company ID (shown on the Company info page of the dashboard) and the API key of your platform
into `COMPANY_ID` and `API_KEY`.

**Key features:**
- Creating a subscription with an idempotency key you keep with your order
- Returning the page that sends the customer to the card registration
- Reading subscription webhooks and the failed-registration notification from the raw request body
- Turning the errors of the SDK into HTTP answers

## Configuration

Before running the examples, update the following values:

```python
# Replace these with your actual credentials
PLATFORM_ID = UUID("00000000-0000-0000-0000-000000000000")  # your platform ID
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

Both examples verify the webhook signature. The webhook body is passed to the SDK exactly as received.

### FastAPI Example

```python
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from polako.sdk import CustomerAddress, CustomerInfo, OrderDetails, OrderItem, PolakoClient

app = FastAPI()

PLATFORM_ID = UUID("00000000-0000-0000-0000-000000000000")  # your platform ID
SECRET_KEY = "your-secret-key"  # your secret key


@app.post("/create-payment")
async def create_payment(data: dict):
    order = OrderDetails(
        currency="RSD",
        language="en",
        order_id=data["order_id"],
        items=[
            OrderItem(
                code=item["code"],
                name=item["name"],
                description=item["description"],
                price=Decimal(item["price"]),
                quantity=item["quantity"],
                tax=item["tax"],
            )
            for item in data["items"]
        ],
        total=Decimal(data["total"]),
    )
    customer_data = data["customer"]
    customer = CustomerInfo(
        first_name=customer_data["first_name"],
        last_name=customer_data["last_name"],
        email=customer_data["email"],
        phone=customer_data["phone"],
        address=CustomerAddress(
            address=customer_data["address"]["street"],
            city=customer_data["address"]["city"],
            state=customer_data["address"]["state"],
            zip=customer_data["address"]["zip"],
            country=customer_data["address"]["country"],
        ),
    )

    async with PolakoClient(test_env=True) as client:
        session = await client.create_order(order, customer, PLATFORM_ID, SECRET_KEY)

    return {"payment_url": session.paymentPageUrl, "session_id": session.paymentSessionId}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    try:
        callback = PolakoClient.parse_payment_callback(payload=body.decode("utf-8"), secret_key=SECRET_KEY)
    except AssertionError:
        raise HTTPException(status_code=400, detail="invalid signature")

    if callback.success:
        pass  # Process successful payment

    return {"status": "ok"}
```

### Quart Example (Async Flask)

```python
from decimal import Decimal
from uuid import UUID

from polako.sdk import CustomerAddress, CustomerInfo, OrderDetails, OrderItem, PolakoClient
from quart import Quart, jsonify, request

app = Quart(__name__)

PLATFORM_ID = UUID("00000000-0000-0000-0000-000000000000")  # your platform ID
SECRET_KEY = "your-secret-key"  # your secret key


@app.route("/create-payment", methods=["POST"])
async def create_payment():
    data = await request.get_json()

    order = OrderDetails(
        currency="RSD",
        language="en",
        order_id=data["order_id"],
        items=[
            OrderItem(
                code=item["code"],
                name=item["name"],
                description=item["description"],
                price=Decimal(item["price"]),
                quantity=item["quantity"],
                tax=item["tax"],
            )
            for item in data["items"]
        ],
        total=Decimal(data["total"]),
    )
    customer_data = data["customer"]
    customer = CustomerInfo(
        first_name=customer_data["first_name"],
        last_name=customer_data["last_name"],
        email=customer_data["email"],
        phone=customer_data["phone"],
        address=CustomerAddress(
            address=customer_data["address"]["street"],
            city=customer_data["address"]["city"],
            state=customer_data["address"]["state"],
            zip=customer_data["address"]["zip"],
            country=customer_data["address"]["country"],
        ),
    )

    async with PolakoClient(test_env=True) as client:
        session = await client.create_order(order, customer, PLATFORM_ID, SECRET_KEY)

    return jsonify({"payment_url": session.paymentPageUrl, "session_id": session.paymentSessionId})


@app.route("/webhook", methods=["POST"])
async def webhook():
    body = await request.get_data()
    try:
        callback = PolakoClient.parse_payment_callback(payload=body.decode("utf-8"), secret_key=SECRET_KEY)
    except AssertionError:
        return "invalid signature", 400

    if callback.success:
        pass  # Process successful payment

    return "", 200
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
