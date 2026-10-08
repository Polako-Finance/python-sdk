"""A local emulator of the gateway for end-to-end tests of the subscription flow.

It is a real HTTP server on a free port, so the SDK talks to it exactly as it talks to the gateway. It models only
what the gateway is documented to do for subscriptions (authentication by the platform API key, idempotency,
validation, the three kinds of registration form, the webhooks and how they are signed and retried); it is not the
gateway and cannot prove anything the real one would do differently.

The order of the checks in the subscribe endpoint follows the gateway: the parameters and the body are validated
first (HTTP 422), then the API key is checked (401, 403), then the rules of the service run: subscriptions are
switched on (409), a repeated idempotency key is answered with the original response, the currency is allowed (422),
the customer has no live subscription for the same reference (409).
"""

import asyncio
import hashlib
import hmac
import json
import math
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

import aiohttp
from aiohttp import web

from tests.factories import make_form_post_response, make_hpp_form_response, make_redirect_form_response
from tests.generators import generate_api_key

KNOWN_CURRENCIES = ("RSD", "RUB", "EUR", "USD")
BILLING_INTERVALS = ("daily", "weekly", "monthly", "quarterly", "yearly")
LIVE_STATUSES = ("active", "paused")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REF_MAX_LENGTH = 128

# (wire name, snake_case name): the gateway accepts both spellings in a request.
FIELDS = [
    ("customerEmail", "customer_email"),
    ("amount", "amount"),
    ("currency", "currency"),
    ("billingInterval", "billing_interval"),
    ("merchantSubscriptionRef", "merchant_subscription_ref"),
    ("successUrl", "success_url"),
    ("cancelUrl", "cancel_url"),
    ("errorUrl", "error_url"),
]

FORM_BUILDERS = {
    "form_post": make_form_post_response,
    "hpp_form_post": make_hpp_form_response,
    "iframe": make_redirect_form_response,
}


@dataclass
class Platform:
    """A merchant's platform as the dashboard creates it."""

    company_id: UUID
    platform_id: UUID
    api_key: str
    callback_url: Optional[str] = None
    # False plays an old subscription that was made without a platform: the gateway cannot sign its notifications
    # and sends no lifecycle webhooks for it.
    links_subscriptions: bool = True


@dataclass
class ReceivedRequest:
    """One request the emulator received, as it arrived."""

    method: str
    path: str
    headers: Dict[str, str]
    body: bytes


@dataclass
class Subscription:
    id: UUID
    company_id: UUID
    platform: Optional[Platform]
    customer_email: str
    amount: Decimal
    currency: str
    billing_interval: str
    merchant_subscription_ref: str
    success_url: str
    cancel_url: str
    error_url: str
    form: Dict[str, Any]
    status: str = "pending_registration"


@dataclass
class Attempt:
    """One try at delivering a webhook: the HTTP status the merchant answered, or the error if it did not."""

    status: Optional[int] = None
    error: Optional[str] = None


@dataclass
class Delivery:
    """A webhook as the emulator sent it, and what came of every attempt."""

    url: str
    payload: Dict[str, Any]
    body: bytes
    signature: Optional[str]
    attempts: List[Attempt] = field(default_factory=list)
    delivered: bool = False


@dataclass
class PlannedFailure:
    """A way the next request to the subscribe endpoint goes wrong before the service looks at it."""

    status: Optional[int] = None
    retry_after: Optional[int] = None
    drop_connection: bool = False


@dataclass
class GatewayTestServer:
    host: str = "127.0.0.1"
    form_type: str = "form_post"
    subscriptions_enabled: bool = True
    allowed_currencies: Optional[List[str]] = None
    # (requests, seconds): more requests than that within the window from one API key get HTTP 429. None: no limit.
    rate_limit: Optional[Tuple[int, int]] = None
    clock: Callable[[], float] = time.monotonic
    platforms: Dict[str, Platform] = field(default_factory=dict)
    subscriptions: Dict[UUID, Subscription] = field(default_factory=dict)
    received_requests: List[ReceivedRequest] = field(default_factory=list)
    base_url: str = ""
    _replies: Dict[Tuple[UUID, str], Dict[str, Any]] = field(default_factory=dict)
    # Webhooks: the real gateway makes up to 3 attempts, waiting 1 s and then 2 s; the emulator does not wait.
    webhook_attempts: int = 3
    webhook_backoff: Tuple[float, ...] = (0.0, 0.0)
    webhook_timeout: float = 10.0
    deliveries: List[Delivery] = field(default_factory=list)
    skipped_webhooks: List[Dict[str, Any]] = field(default_factory=list)
    _planned: List[PlannedFailure] = field(default_factory=list)
    _hits: Dict[str, List[float]] = field(default_factory=dict)
    _provider_rejections: int = 0

    # ------------------------------------------------------------------ what happens to a subscription later

    def activate(self, subscription_id: UUID) -> Subscription:
        """The customer completed the card registration. The merchant gets no webhook for this."""
        subscription = self.subscriptions[subscription_id]
        assert subscription.status == "pending_registration", f"cannot activate a {subscription.status} subscription"
        subscription.status = "active"
        return subscription

    async def charge(
        self,
        subscription_id: UUID,
        *,
        succeeded: bool = True,
        amount: Optional[Decimal] = None,
        error_class: Optional[str] = None,
    ) -> Optional[Delivery]:
        """A scheduled charge of an active subscription went through or failed; the merchant is notified."""
        subscription = self.subscriptions[subscription_id]
        assert subscription.status == "active", f"cannot charge a {subscription.status} subscription"
        base = self._lifecycle_payload(subscription)
        if succeeded:
            payload = {
                "event": "charge_succeeded",
                **base,
                "amount": str(amount if amount is not None else subscription.amount),
                "currency": subscription.currency,
                "charged_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            subscription.status = "past_due"
            payload = {"event": "charge_failed", **base, "error_class": error_class or "card_declined"}
        return await self.send_webhook(subscription, payload)

    async def complete_registration(
        self,
        subscription_id: UUID,
        *,
        succeeded: bool = True,
        error_message: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> Optional[Delivery]:
        """The customer's 3DS registration ends. Success activates the subscription and the merchant hears nothing;
        a failure ends it and the gateway POSTs a notification to the `errorUrl` given when it was created."""
        subscription = self.subscriptions[subscription_id]
        assert subscription.status == "pending_registration", f"cannot finish a {subscription.status} registration"
        if succeeded:
            subscription.status = "active"
            return None
        subscription.status = "registration_failed"
        payload = {
            "order_id": str(subscription.id),
            "subscription_id": str(subscription.id),
            "merchant_subscription_ref": subscription.merchant_subscription_ref,
            "success": 0,
            "error_message": error_message or "The card was declined by the issuer.",
            "provider_name": provider_name or "emulated-provider",
        }
        # One attempt, no retries, to the errorUrl of the subscription; signed only if it belongs to a platform.
        platform = subscription.platform
        return await self._deliver(subscription.error_url, payload, platform.api_key if platform else None, attempts=1)

    async def drop_externally(self, subscription_id: UUID) -> Optional[Delivery]:
        """The card agreement was revoked on the provider's side."""
        subscription = self.subscriptions[subscription_id]
        assert subscription.status in ("active", "past_due"), f"cannot drop a {subscription.status} subscription"
        subscription.status = "dropped_externally"
        return await self.send_webhook(subscription, {"event": "dropped_externally", **self._lifecycle_payload(subscription)})

    async def cancel(self, subscription_id: UUID) -> Optional[Delivery]:
        """The subscription is cancelled in the dashboard."""
        subscription = self.subscriptions[subscription_id]
        assert subscription.status in ("active", "paused", "past_due"), f"cannot cancel a {subscription.status} one"
        subscription.status = "cancelled"
        return await self.send_webhook(subscription, {"event": "cancelled", **self._lifecycle_payload(subscription)})

    @staticmethod
    def _lifecycle_payload(subscription: Subscription) -> Dict[str, Any]:
        return {
            "subscription_id": str(subscription.id),
            "merchant_subscription_ref": subscription.merchant_subscription_ref,
        }

    async def send_webhook(self, subscription: Subscription, payload: Dict[str, Any]) -> Optional[Delivery]:
        """Send a lifecycle webhook to the callback URL of the subscription's platform, the way the gateway does.

        The body is compact JSON with sorted keys and `X-Signature` is its HMAC-SHA256 under the platform API key.
        A success (2xx) ends it; a client error (4xx) is final; a server error (5xx) or a network error is tried
        again, up to `webhook_attempts` times. Nothing is sent, and None is returned, when the platform has no URL.
        """
        platform = subscription.platform
        if platform is None or not platform.callback_url:
            reason = "subscription has no platform" if platform is None else "no callback URL"
            self.skipped_webhooks.append({"subscription_id": subscription.id, "event": payload.get("event"), "reason": reason})
            return None
        return await self._deliver(platform.callback_url, payload, platform.api_key, attempts=self.webhook_attempts)

    async def _deliver(self, url: str, payload: Dict[str, Any], api_key: Optional[str], *, attempts: int) -> Delivery:
        """POST a payload as compact JSON with sorted keys, signed with `X-Signature` when there is a key."""
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        signature = hmac.new(api_key.encode(), body, hashlib.sha256).hexdigest() if api_key else None
        delivery = Delivery(url=url, payload=payload, body=body, signature=signature)
        self.deliveries.append(delivery)
        headers = {"Content-Type": "application/json"}
        if signature:
            headers["X-Signature"] = signature

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.webhook_timeout)) as http:
            for attempt in range(1, attempts + 1):
                try:
                    async with http.post(url, data=body, headers=headers) as response:
                        delivery.attempts.append(Attempt(status=response.status))
                        if 200 <= response.status < 300:
                            delivery.delivered = True
                            return delivery
                        if response.status < 500:
                            return delivery
                except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                    delivery.attempts.append(Attempt(error=repr(error)))
                if attempt < attempts:
                    await asyncio.sleep(self.webhook_backoff[min(attempt - 1, len(self.webhook_backoff) - 1)])
        return delivery

    def fail_next(self, status: int, *, times: int = 1, retry_after: Optional[int] = None) -> None:
        """Answer the next `times` requests with this status, as an outage or a limit in front of the service."""
        self._planned.extend(PlannedFailure(status=status, retry_after=retry_after) for _ in range(times))

    def drop_connection_next(self, *, times: int = 1) -> None:
        """Close the connection of the next `times` requests without an answer."""
        self._planned.extend(PlannedFailure(drop_connection=True) for _ in range(times))

    def reject_registration_next(self, *, times: int = 1) -> None:
        """The card processor refuses the registration request for the next `times` otherwise valid requests."""
        self._provider_rejections += times

    def add_platform(self, **overrides: Any) -> Platform:
        fields: Dict[str, Any] = {"company_id": uuid4(), "platform_id": uuid4(), "api_key": generate_api_key()}
        fields.update(overrides)
        platform = Platform(**fields)
        self.platforms[platform.api_key] = platform
        return platform

    @asynccontextmanager
    async def run(self):
        app = web.Application(middlewares=[self._record])
        app.router.add_post("/v1/company/{company_id}/subscriptions", self._subscribe)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, 0)
        await site.start()
        port = runner.addresses[0][1]
        self.base_url = f"http://{self.host}:{port}"
        try:
            yield self
        finally:
            await runner.cleanup()

    @web.middleware
    async def _record(self, request: web.Request, handler):
        body = await request.read()
        self.received_requests.append(ReceivedRequest(request.method, request.path, dict(request.headers), body))
        return await handler(request)

    # ------------------------------------------------------------------ subscribe

    async def _subscribe(self, request: web.Request) -> web.Response:
        # 0. Things that go wrong in front of the service: a planned outage, a dropped connection, the rate limit.
        if self._planned:
            planned = self._planned.pop(0)
            if planned.drop_connection:
                if request.transport is not None:
                    request.transport.abort()
                raise ConnectionResetError("the emulator dropped the connection")
            headers = {"Retry-After": str(planned.retry_after)} if planned.retry_after is not None else None
            return web.json_response({"detail": "planned failure"}, status=planned.status, headers=headers)
        wait = self._seconds_until_allowed(request.headers.get("company_api_key", ""))
        if wait is not None:
            return web.json_response({"detail": "Too many requests"}, status=429, headers={"Retry-After": str(wait)})

        # 1. The parameters and the body are validated before anything else, like the gateway's framework does.
        try:
            company_id = UUID(request.match_info["company_id"])
        except ValueError:
            return _error(422, "company_id is not a valid UUID")
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if not idempotency_key:
            return _error(422, "Idempotency-Key header is required")
        fields, problems = _read_request(await request.read())
        if problems:
            return _error(422, problems)

        # 2. Authentication by the platform API key.
        api_key = request.headers.get("company_api_key", "").strip()
        if not api_key:
            return _error(401, "Missing company_api_key header.")
        platform = self.platforms.get(api_key)
        if platform is None:
            return _error(401, "Client platform not found for the provided API key.")
        if platform.company_id != company_id:
            return _error(403, "API key does not belong to this company.")

        # 3. The rules of the subscription service.
        if not self.subscriptions_enabled:
            return _error(409, "Subscriptions are not enabled for this company.")
        replay = self._replies.get((company_id, idempotency_key))
        if replay is not None:
            return web.json_response(replay, status=201)
        if self.allowed_currencies and fields["currency"] not in self.allowed_currencies:
            return _error(422, f"Currency {fields['currency']} is not allowed; allowed: {self.allowed_currencies}")
        if self._live_duplicate(company_id, fields["customer_email"], fields["merchant_subscription_ref"]):
            return _error(409, "The customer already has a live subscription for this merchantSubscriptionRef.")
        if self._provider_rejections > 0:
            self._provider_rejections -= 1
            return _error(502, "The payment provider rejected the card registration request.")

        subscription = Subscription(
            id=uuid4(),
            company_id=company_id,
            platform=platform if platform.links_subscriptions else None,
            form=FORM_BUILDERS[self.form_type](),
            **fields,
        )
        self.subscriptions[subscription.id] = subscription
        reply = {"subscriptionId": str(subscription.id), "registrationForm": subscription.form}
        self._replies[(company_id, idempotency_key)] = reply
        return web.json_response(reply, status=201)

    def _seconds_until_allowed(self, api_key: str) -> Optional[int]:
        """Count this request against the rate limit; the seconds to wait if it is over the limit, else None."""
        if self.rate_limit is None:
            return None
        limit, window = self.rate_limit
        now = self.clock()
        hits = [t for t in self._hits.get(api_key, []) if now - t < window]
        if len(hits) >= limit:
            self._hits[api_key] = hits
            return max(1, math.ceil(window - (now - hits[0])))
        hits.append(now)
        self._hits[api_key] = hits
        return None

    def _live_duplicate(self, company_id: UUID, customer_email: str, ref: str) -> bool:
        return any(
            s.company_id == company_id
            and s.customer_email == customer_email
            and s.merchant_subscription_ref == ref
            and s.status in LIVE_STATUSES
            for s in self.subscriptions.values()
        )


def _error(status: int, detail: Any) -> web.Response:
    return web.json_response({"detail": detail}, status=status)


def _http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _read_request(raw: bytes) -> Tuple[Dict[str, Any], List[str]]:
    """Read the body of a subscribe request into snake_case fields; return the problems found, if any."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}, ["the body is not valid JSON"]
    if not isinstance(body, dict):
        return {}, ["the body must be a JSON object"]

    fields: Dict[str, Any] = {}
    problems: List[str] = []
    for wire, snake in FIELDS:
        value = body.get(wire, body.get(snake))
        if value is None:
            problems.append(f"{wire} is required")
        else:
            fields[snake] = value
    if problems:
        return {}, problems

    if not isinstance(fields["customer_email"], str) or not EMAIL.match(fields["customer_email"]):
        problems.append("customerEmail is not a valid email address")
    try:
        if isinstance(fields["amount"], bool):
            raise InvalidOperation
        amount = Decimal(str(fields["amount"]))
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
        fields["amount"] = amount
    except InvalidOperation:
        problems.append("amount must be a number greater than zero")
    if fields["currency"] not in KNOWN_CURRENCIES:
        problems.append(f"currency must be one of {', '.join(KNOWN_CURRENCIES)}")
    if fields["billing_interval"] not in BILLING_INTERVALS:
        problems.append(f"billingInterval must be one of {', '.join(BILLING_INTERVALS)}")
    ref = fields["merchant_subscription_ref"]
    if not isinstance(ref, str) or not 1 <= len(ref) <= REF_MAX_LENGTH:
        problems.append(f"merchantSubscriptionRef must be 1 to {REF_MAX_LENGTH} characters")
    for wire, snake in (("successUrl", "success_url"), ("cancelUrl", "cancel_url"), ("errorUrl", "error_url")):
        if not _http_url(fields[snake]):
            problems.append(f"{wire} must be a valid http or https URL")
    return fields, problems
