"""A merchant's webhook endpoint, written the way the documentation tells a merchant to write it.

It reads the raw request body and hands it to the SDK unchanged. Options exist to play a merchant who does it wrong
(parses the JSON and serializes it again before checking the signature) or whose endpoint is failing.
"""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, List

from aiohttp import web

from polako.sdk import (
    WebhookPayloadError,
    WebhookSignatureError,
    parse_registration_failed,
    parse_subscription_webhook,
)


@dataclass
class MerchantReceiver:
    api_key: str
    host: str = "127.0.0.1"
    # Play a merchant who parses the body and serializes it again before the SDK sees it.
    reserialize: bool = False
    # Play a merchant who also accepts a registration failure that came without a signature.
    allow_unsigned: bool = False
    events: List[Any] = field(default_factory=list)
    failures: List[Any] = field(default_factory=list)
    raw_bodies: List[bytes] = field(default_factory=list)
    signature_errors: List[WebhookSignatureError] = field(default_factory=list)
    payload_errors: List[WebhookPayloadError] = field(default_factory=list)
    base_url: str = ""
    _planned: List[int] = field(default_factory=list)

    @property
    def webhook_url(self) -> str:
        return f"{self.base_url}/polako/subscription-webhook"

    @property
    def error_url(self) -> str:
        return f"{self.base_url}/polako/subscription-error"

    def fail_next(self, status: int, *, times: int = 1) -> None:
        """Answer the next `times` webhooks with this status before looking at them, like a failing endpoint."""
        self._planned.extend([status] * times)

    @asynccontextmanager
    async def run(self):
        app = web.Application()
        app.router.add_post("/polako/subscription-webhook", self._webhook)
        app.router.add_post("/polako/subscription-error", self._registration_error)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, 0)
        await site.start()
        self.base_url = f"http://{self.host}:{runner.addresses[0][1]}"
        try:
            yield self
        finally:
            await runner.cleanup()

    async def _webhook(self, request: web.Request) -> web.Response:
        if self._planned:
            return web.Response(status=self._planned.pop(0))

        body = await request.read()
        self.raw_bodies.append(body)
        if self.reserialize:
            body = json.dumps(json.loads(body), indent=2).encode()
        try:
            event = parse_subscription_webhook(body, request.headers.get("X-Signature"), self.api_key)
        except WebhookSignatureError as error:
            self.signature_errors.append(error)
            return web.Response(status=400, text="invalid signature")
        except WebhookPayloadError as error:
            self.payload_errors.append(error)
            return web.Response(status=422, text="invalid payload")
        self.events.append(event)
        return web.json_response({"status": "ok"})

    async def _registration_error(self, request: web.Request) -> web.Response:
        if self._planned:
            return web.Response(status=self._planned.pop(0))

        body = await request.read()
        self.raw_bodies.append(body)
        try:
            failure = parse_registration_failed(
                body, request.headers.get("X-Signature"), self.api_key, allow_unsigned=self.allow_unsigned
            )
        except WebhookSignatureError as error:
            self.signature_errors.append(error)
            return web.Response(status=400, text="invalid signature")
        except WebhookPayloadError as error:
            self.payload_errors.append(error)
            return web.Response(status=422, text="invalid payload")
        self.failures.append(failure)
        return web.json_response({"status": "ok"})
