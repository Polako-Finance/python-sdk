"""A merchant's back office for subscriptions: list them, look at one, pause, resume and cancel.

Run it:

    pip install polako-finance fastapi uvicorn
    uvicorn subscription_management_example:app --port 8001

Then look at the subscriptions of your company, one page at a time:

    curl "http://localhost:8001/subscriptions?status=active&limit=20"

Use an ID from that list to see one subscription with its charges, or to change it:

    curl http://localhost:8001/subscriptions/<an ID from the list>
    curl -X POST http://localhost:8001/subscriptions/<an ID from the list>/pause

This server is the part of your system a person (or your support tool) uses. Put it behind your own sign-in: anyone who
can reach it can cancel your customers' subscriptions.
"""

from contextlib import contextmanager
from typing import Iterator, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from polako.sdk import (
    ConflictError,
    ForbiddenError,
    HttpClientError,
    HttpRequestError,
    NotFoundError,
    PolakoClient,
    RateLimitedError,
    SubscriptionStatus,
)

COMPANY_ID = UUID("00000000-0000-0000-0000-000000000000")  # your company ID
API_KEY = "your-secret-key"  # the API key of your platform

app = FastAPI()


def new_client() -> PolakoClient:
    return PolakoClient(test_env=True, company_id=COMPANY_ID, api_key=API_KEY)


@contextmanager
def as_http_answers() -> Iterator[None]:
    """Turn what the SDK raises into the answer this server gives."""
    try:
        yield
    except NotFoundError:
        raise HTTPException(status_code=404, detail="There is no such subscription")
    except ForbiddenError:
        raise HTTPException(status_code=403, detail="This subscription belongs to another company")
    except ConflictError as error:
        # Not in a status that allows the change (resuming an active subscription, say), or subscriptions are switched
        # off for your company. The body of the answer says which.
        raise HTTPException(status_code=409, detail=error.response_body)
    except RateLimitedError:
        raise HTTPException(status_code=429, detail="Too many requests, try again in a minute")
    except HttpRequestError as error:
        raise HTTPException(status_code=502, detail=f"The payment gateway answered with status {error.status_code}")
    except HttpClientError:
        # A change may or may not have been made. The SDK does not repeat it: look at the subscription first.
        raise HTTPException(status_code=503, detail="The payment gateway cannot be reached. Check the subscription.")


@app.get("/subscriptions")
async def list_subscriptions(
    status: Optional[SubscriptionStatus] = None,
    search: str = "",
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    async with new_client() as client:
        with as_http_answers():
            page = await client.list_subscriptions(status=status, search=search or None, limit=limit, offset=offset)

    return {
        "total": page.total,
        "items": [
            {
                "id": str(item.id),
                "email": item.customer_email,
                "status": item.status,
                "amount": str(item.amount),
                "currency": item.currency,
                "next_charge_at": item.next_charge_at.isoformat() if item.next_charge_at else "",
            }
            for item in page.items
        ],
    }


@app.get("/subscriptions/{subscription_id}")
async def subscription(subscription_id: UUID):
    async with new_client() as client:
        with as_http_answers():
            details = await client.get_subscription(subscription_id)

    return {
        "id": str(details.id),
        "status": details.status,
        "email": details.customer.email,
        "card": details.saved_card.masked_pan if details.saved_card else "no card yet",
        "charges": [
            {
                "date": charge.charge_date.isoformat(),
                "status": charge.status,
                "amount": str(charge.amount),
                # what you pass to refund_session to return this charge
                "payment_session_id": str(charge.payment_session_id),
            }
            for charge in details.charge_history
        ],
        "events": [{"type": event.event_type, "at": event.created_at.isoformat()} for event in details.events],
    }


@app.post("/subscriptions/{subscription_id}/pause", status_code=204)
async def pause(subscription_id: UUID):
    async with new_client() as client:
        with as_http_answers():
            await client.pause_subscription(subscription_id)


@app.post("/subscriptions/{subscription_id}/resume", status_code=204)
async def resume(subscription_id: UUID):
    async with new_client() as client:
        with as_http_answers():
            await client.resume_subscription(subscription_id)


@app.post("/subscriptions/{subscription_id}/cancel", status_code=204)
async def cancel(subscription_id: UUID):
    async with new_client() as client:
        with as_http_answers():
            await client.cancel_subscription(subscription_id)
