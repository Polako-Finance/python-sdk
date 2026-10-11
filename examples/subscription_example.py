"""A merchant's server for subscriptions.

It creates a subscription, sends the customer to the card registration, and reads the notifications the gateway sends
afterwards: every charge, a card that was revoked, a cancellation, and a card registration that failed.

Run it (the gateway has to reach the two notification URLs, so SHOP_URL must be an address it can open, for example a
tunnel to your machine while you try this out):

    pip install polako-finance fastapi uvicorn
    uvicorn subscription_example:app --port 8000

Start a subscription with:

    curl -X POST "http://localhost:8000/subscribe?email=jane.smith@example.com"

and open the page it returns in a browser. Then look at http://localhost:8000/subscriptions.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from polako.sdk import (
    BillingInterval,
    ChargeFailed,
    ChargeSucceeded,
    ConflictError,
    DroppedExternally,
    HttpClientError,
    HttpRequestError,
    PolakoClient,
    RateLimitedError,
    RequestValidationError,
    SubscriptionCancelled,
    WebhookPayloadError,
    WebhookSignatureError,
    parse_registration_failed,
    parse_subscription_webhook,
    render_registration_form,
)

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000000")  # your company ID
API_KEY = "your-secret-key"  # the API key of your platform
SHOP_URL = "https://shop.example.com"  # where this server can be reached from the internet

app = FastAPI()

# A stand-in for your database: what you know about every subscription, by the subscription ID the gateway gave it.
SUBSCRIPTIONS: dict = {}


def remember(subscription_id: UUID, **facts: str) -> None:
    SUBSCRIPTIONS.setdefault(str(subscription_id), {}).update(facts)


@app.post("/subscribe")
async def subscribe(email: str):
    # Make the key first and keep it with your order. If this server stops before it hears the answer, ask again with
    # the same key and the gateway returns the same subscription instead of creating a second one.
    key = str(uuid4())
    async with PolakoClient(test_env=True, company_id=COMPANY_ID, api_key=API_KEY) as client:
        try:
            created = await client.create_subscription(
                customer_email=email,
                amount=Decimal("990.00"),
                currency="RSD",
                billing_interval=BillingInterval.MONTHLY,
                merchant_subscription_ref="plan-pro-monthly",
                success_url=f"{SHOP_URL}/subscribe/success",
                cancel_url=f"{SHOP_URL}/subscribe/cancel",
                error_url=f"{SHOP_URL}/polako/subscription-error",
                idempotency_key=key,
            )
        except ConflictError:
            raise HTTPException(status_code=409, detail="This customer already has this subscription")
        except RateLimitedError:
            raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
        except RequestValidationError as error:
            raise HTTPException(status_code=400, detail=error.response_body)
        except HttpRequestError as error:
            raise HTTPException(status_code=502, detail=f"The payment gateway answered with status {error.status_code}")
        except HttpClientError:
            raise HTTPException(status_code=503, detail="The payment gateway cannot be reached")

    remember(created.subscription_id, email=email, status="waiting for the card registration", idempotency_key=key)
    # A page that sends the customer to the card registration. It is only the customer who completes it.
    return HTMLResponse(render_registration_form(created.registration_form))


@app.get("/subscribe/success")
async def subscribe_success():
    return PlainTextResponse("Thank you. Your subscription is being activated.")


@app.get("/subscribe/cancel")
async def subscribe_cancel():
    return PlainTextResponse("The card registration was cancelled. You have not been charged.")


@app.post("/polako/subscription-webhook")
async def subscription_webhook(request: Request):
    # Read the raw body: the signature is checked over exactly these bytes.
    try:
        event = parse_subscription_webhook(await request.body(), request.headers.get("X-Signature"), API_KEY)
    except WebhookSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    except WebhookPayloadError:
        raise HTTPException(status_code=422, detail="invalid payload")

    if isinstance(event, ChargeSucceeded):
        remember(event.subscription_id, status="active", last_charge=f"{event.amount} {event.currency}")
    elif isinstance(event, ChargeFailed):
        remember(event.subscription_id, status=f"payment failed ({event.error_class})")
    elif isinstance(event, DroppedExternally):
        remember(event.subscription_id, status="the card was revoked by the card provider")
    elif isinstance(event, SubscriptionCancelled):
        remember(event.subscription_id, status="cancelled")
    # Anything else is a kind of event this version of the SDK does not know; it is acknowledged and ignored.
    return {"status": "ok"}


@app.post("/polako/subscription-error")
async def subscription_error(request: Request):
    try:
        failure = parse_registration_failed(await request.body(), request.headers.get("X-Signature"), API_KEY)
    except WebhookSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    except WebhookPayloadError:
        raise HTTPException(status_code=422, detail="invalid payload")

    remember(failure.subscription_id, status=f"card registration failed: {failure.error_message}")
    return {"status": "ok"}


@app.get("/subscriptions")
async def subscriptions():
    return SUBSCRIPTIONS
