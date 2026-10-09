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
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

import aiohttp
from aiohttp import web

from tests.factories import make_form_post_response, make_hpp_form_response, make_redirect_form_response
from tests.generators import generate_api_key, generate_random_digit_string, generate_readable_string

KNOWN_CURRENCIES = ("RSD", "RUB", "EUR", "USD")
BILLING_INTERVALS = ("daily", "weekly", "monthly", "quarterly", "yearly")
LIVE_STATUSES = ("active", "paused")
SUBSCRIPTION_STATUSES = ("pending_registration", "registration_failed", "active", "past_due", "paused", "cancelled")
SORT_FIELDS = ("created_at", "next_charge_at", "last_charged_at", "amount", "status")
INTERVAL_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91, "yearly": 365}
# the statuses each change is allowed from, as the subscription state machine has them
CHANGE_FROM = {"pause": ("active",), "resume": ("paused",), "cancel": ("active", "paused", "past_due")}
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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    customer_id: UUID = field(default_factory=uuid4)
    external_customer_id: str = field(default_factory=lambda: generate_readable_string(12))
    card: Optional[Dict[str, Any]] = None
    anchor_at: Optional[datetime] = None
    next_charge_at: Optional[datetime] = None
    last_charged_at: Optional[datetime] = None
    charges: List[Dict[str, Any]] = field(default_factory=list)
    journal: List[Dict[str, Any]] = field(default_factory=list)


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
        self._activate(subscription)
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
        self._book_charge(subscription, succeeded, amount, error_class or "card_declined")
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
            self._activate(subscription)
            return None
        subscription.status = "registration_failed"
        self._note(subscription, "registration_failed")
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
        self._note(subscription, "dropped_externally")
        return await self.send_webhook(subscription, {"event": "dropped_externally", **self._lifecycle_payload(subscription)})

    async def cancel(self, subscription_id: UUID) -> Optional[Delivery]:
        """The subscription is cancelled in the dashboard."""
        subscription = self.subscriptions[subscription_id]
        assert subscription.status in ("active", "paused", "past_due"), f"cannot cancel a {subscription.status} one"
        subscription.status = "cancelled"
        subscription.next_charge_at = None
        self._note(subscription, "cancelled")
        return await self.send_webhook(subscription, {"event": "cancelled", **self._lifecycle_payload(subscription)})

    def _note(self, subscription: Subscription, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """An entry in the subscription's journal."""
        subscription.journal.append(
            {"id": str(uuid4()), "eventType": event_type, "payload": payload, "createdAt": _moment(datetime.now(timezone.utc))}
        )

    def _activate(self, subscription: Subscription) -> None:
        """The card registration succeeded: the subscription is live, has a card and a next charge."""
        now = datetime.now(timezone.utc)
        subscription.status = "active"
        subscription.anchor_at = now
        subscription.next_charge_at = now + timedelta(days=INTERVAL_DAYS[subscription.billing_interval])
        subscription.card = {
            "id": str(uuid4()),
            "maskedPan": f"{generate_random_digit_string(6)}******{generate_random_digit_string(4)}",
            "cardBrand": "VISA",
            "panExpiry": "12/35",
            "status": "active",
        }
        self._note(subscription, "created")

    def _book_charge(self, subscription: Subscription, succeeded: bool, amount: Optional[Decimal], error_class: str) -> None:
        """One scheduled charge, in the history and in the journal."""
        now = datetime.now(timezone.utc)
        subscription.charges.append(
            {
                "id": str(uuid4()),
                "chargeDate": now.date().isoformat(),
                "orderId": generate_readable_string(12),
                "status": "succeeded" if succeeded else "failed",
                "resultCode": "000" if succeeded else "051",
                "errorClass": None if succeeded else error_class,
                "errorMessage": None if succeeded else "The card was declined.",
                "amount": str(amount if amount is not None else subscription.amount),
                "retryCount": 0,
                "reconcileCount": 0,
                "nextRetryAt": None,
                "createdAt": _moment(now),
                "updatedAt": _moment(now),
                "paymentSessionId": str(uuid4()),
            }
        )
        if succeeded:
            subscription.last_charged_at = now
            subscription.next_charge_at = now + timedelta(days=INTERVAL_DAYS[subscription.billing_interval])
            self._note(subscription, "charge_succeeded")
        else:
            self._note(subscription, "charge_failed")
            self._note(subscription, "past_due")

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
        app.router.add_get("/v1/company/{company_id}/subscriptions", self._list)
        app.router.add_get("/v1/company/{company_id}/subscriptions/{subscription_id}", self._detail)
        for action in CHANGE_FROM:
            path = f"/v1/company/{{company_id}}/subscriptions/{{subscription_id}}/{action}"
            app.router.add_patch(path, self._change(action))
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
        planned_response = self._planned_response(request)
        if planned_response is not None:
            return planned_response
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

    def _planned_response(self, request: web.Request) -> Optional[web.Response]:
        """The next planned failure, if any: an outage answer, or a connection dropped without one."""
        if not self._planned:
            return None
        planned = self._planned.pop(0)
        if planned.drop_connection:
            if request.transport is not None:
                request.transport.abort()
            raise ConnectionResetError("the emulator dropped the connection")
        headers = {"Retry-After": str(planned.retry_after)} if planned.retry_after is not None else None
        return web.json_response({"detail": "planned failure"}, status=planned.status, headers=headers)

    # ------------------------------------------------------------------ read and manage

    def _caller(self, request: web.Request) -> Tuple[Optional[web.Response], Optional[UUID]]:
        """Who is calling a company's route: the platform behind the API key, and only for its own company."""
        try:
            company_id = UUID(request.match_info["company_id"])
        except ValueError:
            return _error(422, "company_id is not a valid UUID"), None
        api_key = request.headers.get("company_api_key", "").strip()
        if not api_key:
            return _error(401, "Authentication required."), None
        platform = self.platforms.get(api_key)
        if platform is None:
            return _error(401, "Client platform not found for the provided API key."), None
        if platform.company_id != company_id:
            return _error(403, "API key does not belong to this company."), None
        return None, company_id

    def _owned(self, request: web.Request, company_id: UUID) -> Tuple[Optional[web.Response], Optional[Subscription]]:
        """The subscription in the path, if there is one and it is the company's."""
        try:
            subscription_id = UUID(request.match_info["subscription_id"])
        except ValueError:
            return _error(422, "subscription_id is not a valid UUID"), None
        subscription = self.subscriptions.get(subscription_id)
        if subscription is None:
            return _error(404, "Subscription not found"), None
        if subscription.company_id != company_id:
            return _error(403, "Subscription does not belong to this company"), None
        return None, subscription

    async def _detail(self, request: web.Request) -> web.Response:
        planned = self._planned_response(request)
        if planned is not None:
            return planned
        refusal, company_id = self._caller(request)
        if refusal is not None:
            return refusal
        refusal, subscription = self._owned(request, company_id)
        if refusal is not None:
            return refusal
        return web.json_response(_detail_json(subscription))

    async def _list(self, request: web.Request) -> web.Response:
        planned = self._planned_response(request)
        if planned is not None:
            return planned
        refusal, company_id = self._caller(request)
        if refusal is not None:
            return refusal
        search, problem = _read_list_query(request.query)
        if problem is not None:
            return problem

        mine = [s for s in self.subscriptions.values() if s.company_id == company_id]
        matching = [s for s in mine if search.accepts(s)]
        ordered = search.order(matching, list(self.subscriptions).index)
        page = ordered[search.offset : search.offset + search.limit]
        return web.json_response({"items": [_summary_json(s) for s in page], "total": len(ordered), "page_size": search.limit})

    def _change(self, action: str):
        async def handler(request: web.Request) -> web.Response:
            planned = self._planned_response(request)
            if planned is not None:
                return planned
            refusal, company_id = self._caller(request)
            if refusal is not None:
                return refusal
            refusal, subscription = self._owned(request, company_id)
            if refusal is not None:
                return refusal
            if not self.subscriptions_enabled:
                return _error(409, "Subscriptions are not enabled for this company.")
            if subscription.status not in CHANGE_FROM[action]:
                return _error(409, f"Subscription is {subscription.status}; it cannot be changed with {action}.")
            if action == "pause":
                subscription.status = "paused"
                self._note(subscription, "paused")
            elif action == "resume":
                subscription.status = "active"
                self._note(subscription, "resumed")
            else:
                await self.cancel(subscription.id)
            return web.Response(status=204)

        return handler

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


def _moment(moment: datetime) -> str:
    """A time as the server writes it: ISO 8601, UTC, a trailing `Z`."""
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary_json(s: Subscription) -> Dict[str, Any]:
    return {
        "id": str(s.id),
        "customerId": str(s.customer_id),
        "customerEmail": s.customer_email,
        "merchantSubscriptionRef": s.merchant_subscription_ref,
        "amount": str(s.amount),
        "currency": s.currency,
        "billingInterval": s.billing_interval,
        "status": s.status,
        "nextChargeAt": _moment(s.next_charge_at) if s.next_charge_at else None,
        "lastChargedAt": _moment(s.last_charged_at) if s.last_charged_at else None,
        "createdAt": _moment(s.created_at),
    }


def _detail_json(s: Subscription) -> Dict[str, Any]:
    failed = [charge for charge in s.charges if charge["status"] == "failed"]
    return {
        "id": str(s.id),
        "customer": {"id": str(s.customer_id), "externalCustomerId": s.external_customer_id, "email": s.customer_email},
        "savedCard": s.card,
        "merchantSubscriptionRef": s.merchant_subscription_ref,
        "amount": str(s.amount),
        "currency": s.currency,
        "billingInterval": s.billing_interval,
        "status": s.status,
        "anchorAt": _moment(s.anchor_at) if s.anchor_at else None,
        "nextChargeAt": _moment(s.next_charge_at) if s.next_charge_at else None,
        "lastChargedAt": _moment(s.last_charged_at) if s.last_charged_at else None,
        "createdAt": _moment(s.created_at),
        "failedChargeCount": len(failed),
        "lastFailedChargeAt": failed[-1]["createdAt"] if failed else None,
        "chargeHistory": list(reversed(s.charges)),  # newest first
        "events": list(s.journal),  # oldest first
    }


@dataclass
class ListQuery:
    """What a list request asks for, once it has been read and found valid."""

    statuses: List[str]
    intervals: List[str]
    text: Optional[str]
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    sort_by: str
    descending: bool
    limit: int
    offset: int

    def accepts(self, s: Subscription) -> bool:
        if self.statuses and s.status not in self.statuses:
            return False
        if self.intervals and s.billing_interval not in self.intervals:
            return False
        if self.date_from and s.created_at < self.date_from:
            return False
        if self.date_to and s.created_at > self.date_to:
            return False
        if self.text:
            needle = self.text.casefold()
            haystack = (s.customer_email, s.merchant_subscription_ref, str(s.id))
            return any(needle in value.casefold() for value in haystack)
        return True

    def order(self, subscriptions: List[Subscription], position: Callable[[UUID], int]) -> List[Subscription]:
        """Sorted by the chosen field; unset times go last when ascending (as the database does), ties by creation."""

        def key(s: Subscription):
            value = getattr(s, self.sort_by)
            return (value is None, value if value is not None else 0, position(s.id))

        return sorted(subscriptions, key=key, reverse=self.descending)


def _read_list_query(query) -> Tuple[Optional[ListQuery], Optional[web.Response]]:
    """Read the query string of a list request; the answer to give instead if it is not valid."""
    try:
        limit, offset = int(query.get("limit", "10")), int(query.get("offset", "0"))
    except ValueError:
        return None, _error(422, "limit and offset must be integers")
    if not 1 <= limit <= 100 or offset < 0:
        return None, _error(422, "limit must be 1 to 100 and offset must not be negative")
    statuses, intervals = query.getall("status", []), query.getall("billing_interval", [])
    if any(value not in SUBSCRIPTION_STATUSES for value in statuses):
        return None, _error(422, f"status must be one of {', '.join(SUBSCRIPTION_STATUSES)}")
    if any(value not in BILLING_INTERVALS for value in intervals):
        return None, _error(422, f"billing_interval must be one of {', '.join(BILLING_INTERVALS)}")
    sort_by, sort_order = query.get("sort_by") or "created_at", query.get("sort_order") or "desc"
    if sort_by not in SORT_FIELDS:
        return None, _error(400, f"Invalid sort_by '{sort_by}'. Allowed values: {sorted(SORT_FIELDS)}.")
    if sort_order not in ("asc", "desc"):
        return None, _error(400, f"Invalid sort_order '{sort_order}'. Allowed values: ['asc', 'desc'].")
    try:
        date_from = _read_bound(query.get("date_from"), end_of_day=False)
        date_to = _read_bound(query.get("date_to"), end_of_day=True)
    except ValueError as error:
        return None, _error(400, str(error))
    return (
        ListQuery(statuses, intervals, query.get("filter"), date_from, date_to, sort_by, sort_order == "desc", limit, offset),
        None,
    )


def _read_bound(value: Optional[str], *, end_of_day: bool) -> Optional[datetime]:
    """A day or a moment (ISO 8601) as an instant; a bare day means its start, or its end for an upper bound."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid ISO 8601 format. Expected: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS[Z|+HH:MM].") from None
    if "T" not in value and end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
