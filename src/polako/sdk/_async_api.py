"""Async API client for Polako Finance."""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, TypeVar, Union
from uuid import UUID, uuid4

from polako.sdk._async_client import AsyncHttpClient
from polako.sdk._constants import BillingInterval, SubscriptionStatus
from polako.sdk._exceptions import ConfigurationError
from polako.sdk._order import (
    CheckStatusRequest,
    CreateOrderRequest,
    CustomerAddress,
    CustomerInfo,
    InitCustomerInfo,
    OrderDetails,
    OrderStatusResponse,
    PaymentCallback,
    PaymentCallbackRaw,
    PaymentSessionDetails,
    PaymentUrlRequest,
    PaymentUrlResult,
    RefundItem,
    RefundRequest,
    RefundResponse,
    SessionInfo,
    SignedPaymentCallbackRaw,
)
from polako.sdk._subscription import SubscribeRequest, SubscribeResponse, SubscriptionCreated
from polako.sdk._subscription_detail import SubscriptionDetails
from polako.sdk._subscription_list import SubscriptionListQuery, SubscriptionListResponse, SubscriptionPage
from polako.sdk._validation import check_subscription_id

T = TypeVar("T")


class AsyncPolakoClient:
    """
    Async SDK client for the Polako Finance payment gateway.

    This client provides a high-level async interface to interact with the payment gateway API.
    Can be used as a context manager for automatic resource cleanup.

    Example:
        async with AsyncPolakoClient() as client:
            session = await client.create_order(order, customer, platform_id, secret_key)
    """

    def __init__(
        self,
        timeout: float = 30.0,
        test_env: bool = False,
        company_id: Optional[UUID] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the async Polako Finance client.

        Args:
            timeout: Request timeout in seconds (default: 30.0)
            test_env: If True, use test environment URL; otherwise use production (default: False)
            company_id: Your company ID. Needed for subscriptions (it is part of the request URL)
            api_key: The API key of your platform, the same value as the ``secret_key`` of the signed
                payment methods. Needed for subscriptions; it is sent only with subscription calls
        """
        from polako.sdk._constants import BASE_URL_PROD, BASE_URL_TEST

        self._http_client = AsyncHttpClient(
            base_url=BASE_URL_TEST if test_env else BASE_URL_PROD,
            timeout=timeout,
        )
        self._company_id = company_id
        self._api_key = api_key

    def __repr__(self) -> str:
        """Show the company ID but never the API key."""
        key = "'***'" if self._api_key else None
        return f"{type(self).__name__}(company_id={self._company_id!r}, api_key={key})"

    async def __aenter__(self) -> "AsyncPolakoClient":
        """Enter async context manager."""
        await self._http_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager."""
        await self._http_client.__aexit__(exc_type, exc_val, exc_tb)

    async def create_order(
        self,
        order: OrderDetails,
        customer: CustomerInfo,
        platform_id: UUID,
        secret_key: str,
    ) -> SessionInfo:
        """
        Create a new order in the payment gateway asynchronously.

        Args:
            order: Order details containing items, totals, and metadata
            customer: Customer information including contact and address details
            platform_id: Platform identifier UUID for authentication
            secret_key: Secret key used for generating request signature

        Returns:
            SessionInfo containing payment session details

        Raises:
            ValueError: If validation of order or customer fails
            HttpRequestError: If the API request fails
            HttpClientError: If there's a network error
        """
        # Validate both arguments before sending request
        order.validate()
        customer.validate()

        from polako.sdk._constants import CURRENCIES, DEFAULT_LANGUAGE

        # Prepare values
        currency = order.currency or next(iter(CURRENCIES))
        language = order.language or DEFAULT_LANGUAGE
        total = order.total.quantize(Decimal("0.01"))

        # Create signature
        signature = self._create_signature(
            f"{order.order_id}|{total:.2f}|{currency}",
            secret_key,
        )

        # Create request payload using Serializable model
        request = CreateOrderRequest(
            platform_id=platform_id,
            currency=currency,
            language=language,
            order_id=order.order_id,
            customer=customer.to_dict(),
            items=[item.to_dict() for item in order.items],
            total=total,
            response="object",
            signature=signature,
        )

        # Send POST request to create order
        return await self._http_client.post(
            "/v1/session/signed",
            request_body=request,
            response_model=SessionInfo,
        )

    async def get_session_details(
        self,
        session_id: UUID,
    ) -> PaymentSessionDetails:
        """
        Get detailed information about a payment session.

        Args:
            session_id: Payment session UUID

        Returns:
            PaymentSessionDetails containing session info, customer, cart, and payment options

        Raises:
            HttpRequestError: If the API request fails (e.g., 404 if session not found, 410 if expired)
            HttpClientError: If there's a network error
        """
        return await self._http_client.get(
            f"/v1/session/{session_id}",
            response_model=PaymentSessionDetails,
        )

    async def get_payment_url(
        self,
        session_id: UUID,
        payment_option_id: UUID,
        customer: InitCustomerInfo,
        language_code: str,
        terms_accepted: bool,
        address_shipping: Optional[CustomerAddress] = None,
    ) -> PaymentUrlResult:
        """
        Get a payment URL for an existing payment session.

        This initiates the payment process by selecting a payment option and
        providing customer details, returning a URL to redirect the customer.

        Args:
            session_id: Payment session UUID (from create_order)
            payment_option_id: UUID of the selected payment option
            customer: Customer information with required first_name, last_name, email
            language_code: Language code for the payment page ('sr', 'en', or 'ru')
            terms_accepted: Whether the customer accepted the terms of service
            address_shipping: Optional shipping address

        Returns:
            PaymentUrlResult containing the payment URL and gateway metadata

        Raises:
            ValueError: If validation of customer info fails
            HttpRequestError: If the API request fails
            HttpClientError: If there's a network error
        """
        customer.validate()

        request = PaymentUrlRequest(
            payment_option_id=payment_option_id,
            customer=customer.to_dict(),
            address_shipping=address_shipping.to_dict() if address_shipping else None,
            language_code=language_code,
            terms_accepted=terms_accepted,
        )

        return await self._http_client.post(
            f"/v1/session/{session_id}/payment_url",
            request_body=request,
            response_model=PaymentUrlResult,
        )

    async def refund_session(
        self,
        session_id: UUID,
        platform_id: UUID,
        secret_key: str,
        reason: str,
        refund_items: Optional[List[RefundItem]] = None,
    ) -> RefundResponse:
        """
        Refund a payment session (full or partial).

        If refund_items is None, a full refund is performed. Otherwise, a partial
        refund is performed for the specified items.

        Args:
            session_id: Payment session UUID to refund
            platform_id: Platform identifier UUID for authentication
            secret_key: Secret key used for generating request signature
            reason: Reason for the refund (3-255 characters)
            refund_items: Optional list of RefundItem for partial refund.
                          If None, all remaining items are refunded.

        Returns:
            RefundResponse containing refund transaction details

        Raises:
            ValueError: If reason is too short/long or refund_items is empty
            HttpRequestError: If the API request fails
            HttpClientError: If there's a network error
        """
        if not reason or len(reason) < 3:
            raise ValueError("'reason' must be at least 3 characters")
        if len(reason) > 255:
            raise ValueError("'reason' must be at most 255 characters")
        if refund_items is not None and len(refund_items) == 0:
            raise ValueError("'refund_items' must not be empty; pass None for a full refund")

        is_full_refund = refund_items is None

        signature = self._create_signature(
            f"refund|{session_id}|{platform_id}",
            secret_key,
        )

        request = RefundRequest(
            platform_id=platform_id,
            session_id=session_id,
            is_full_refund=is_full_refund,
            reason=reason,
            signature=signature,
            refund_items=refund_items if not is_full_refund else None,
        )

        return await self._http_client.post(
            f"/v1/session/{session_id}/refund/signed",
            request_body=request,
            response_model=RefundResponse,
        )

    async def check_order_status(
        self,
        session_id: UUID,
        platform_id: UUID,
        secret_key: str,
    ) -> OrderStatusResponse:
        """
        Check the status of a payment session.

        Args:
            session_id: Payment session UUID to check
            platform_id: Platform identifier UUID for authentication
            secret_key: Secret key used for generating request signature

        Returns:
            OrderStatusResponse containing session status and details

        Raises:
            HttpRequestError: If the API request fails
            HttpClientError: If there's a network error
        """
        signature = self._create_signature(
            f"status|{session_id}|{platform_id}",
            secret_key,
        )

        request = CheckStatusRequest(
            platform_id=platform_id,
            session_id=session_id,
            signature=signature,
        )

        return await self._http_client.post(
            f"/v1/session/{session_id}/status/signed",
            request_body=request,
            response_model=OrderStatusResponse,
        )

    async def create_subscription(
        self,
        *,
        customer_email: str,
        amount: Decimal,
        currency: str,
        billing_interval: BillingInterval,
        merchant_subscription_ref: str,
        success_url: str,
        cancel_url: str,
        error_url: str,
        idempotency_key: Optional[str] = None,
    ) -> SubscriptionCreated:
        """
        Create a subscription and get the form that sends the customer through the card registration (3DS).

        The client must be created with ``company_id`` and ``api_key``. The subscription becomes active only
        after the customer completes the registration; you learn about the result from the webhooks.

        Pass your own ``idempotency_key`` (a UUID is recommended) and store it before the call: sending the same
        request again with the same key returns the same subscription instead of creating a second one. Without
        it a key is generated and returned in the result. A failed attempt (a network error or timeout, or HTTP 429,
        500, 502, 503 or 504) is repeated with the same key, up to 3 attempts in all, so with the default 30 s timeout a
        call can take about 100 s before it gives up (there is no overall deadline). The endpoint accepts 20 requests
        per 60 seconds, and every attempt counts against that limit.

        Args:
            customer_email: Email of the customer
            amount: Amount charged every billing interval, greater than zero
            currency: Currency code, e.g. ``"RSD"``
            billing_interval: How often the customer is charged; a ``BillingInterval`` or its string value
            merchant_subscription_ref: Your own reference of the plan or product (1 to 128 characters). A customer
                can have only one live subscription per reference
            success_url: Where the customer returns after a successful registration
            cancel_url: Where the customer returns after cancelling
            error_url: URL that receives a POST when the registration fails
            idempotency_key: Optional key that makes the call safe to repeat

        Returns:
            SubscriptionCreated with the subscription ID, the registration form and the idempotency key used

        Raises:
            ConfigurationError: Client configuration errors, e.g. the client has no ``company_id`` or ``api_key``
            ValueError: Input validation errors, e.g. ``amount`` is not greater than zero
            UnauthorizedError: If the API key is unknown (HTTP 401)
            ForbiddenError: If the API key belongs to another company (HTTP 403)
            ConflictError: If subscriptions are off for the company or the customer already has this subscription (HTTP 409)
            RequestValidationError: If the server rejects a field, e.g. a currency that is not allowed (HTTP 422)
            RateLimitedError: If the rate limit is hit and the wait is too long to retry (HTTP 429)
            ServerError: If the gateway or the card processor fails (HTTP 5xx)
            HttpClientError: If there is a network error
        """
        credentials = self._subscription_credentials()

        try:
            interval = BillingInterval(billing_interval)
        except ValueError:
            allowed = ", ".join(i.value for i in BillingInterval)
            raise ValueError(f"invalid 'billing_interval' value {billing_interval!r}, must be one of {allowed}") from None

        if idempotency_key is not None and not idempotency_key.strip():
            raise ValueError("'idempotency_key' must not be empty")

        request = SubscribeRequest(
            customer_email=customer_email,
            amount=amount,
            currency=currency,
            billing_interval=interval,
            merchant_subscription_ref=merchant_subscription_ref,
            success_url=success_url,
            cancel_url=cancel_url,
            error_url=error_url,
        )
        request.validate()
        request.amount = Decimal(format(request.amount, "f"))  # plain digits, never an exponent

        key = idempotency_key or str(uuid4())
        response = await self._http_client.post(
            f"/v1/company/{self._company_id}/subscriptions",
            request_body=request,
            response_model=SubscribeResponse,
            headers={**credentials, "Idempotency-Key": key},
        )
        return SubscriptionCreated(
            subscription_id=response.subscription_id,
            registration_form=response.registration_form,
            idempotency_key=key,
        )

    def _subscription_credentials(self) -> Dict[str, str]:
        """The header that identifies the platform on subscription calls; the client must be configured for them."""
        if self._company_id is None:
            raise ConfigurationError("'company_id' is required for subscriptions: pass it to the client constructor")
        if not self._api_key:
            raise ConfigurationError("'api_key' is required for subscriptions: pass it to the client constructor")
        return {"company_api_key": self._api_key}

    async def get_subscription(self, subscription_id: Union[UUID, str]) -> SubscriptionDetails:
        """
        Read one subscription: its customer, card, charge history (newest first) and event journal (oldest first).

        The client must be created with ``company_id`` and ``api_key``. Reading works even when subscriptions are
        switched off for the company. The call is not retried: a failed attempt is raised as it is.

        Args:
            subscription_id: The ID of the subscription, as a ``UUID`` or a string holding one

        Returns:
            SubscriptionDetails

        Raises:
            ConfigurationError: Client configuration errors, e.g. the client has no ``company_id`` or ``api_key``
            ValueError: Input validation errors, e.g. ``subscription_id`` is not a UUID
            UnauthorizedError: If the API key is unknown (HTTP 401)
            ForbiddenError: If the API key or the subscription belongs to another company (HTTP 403)
            NotFoundError: If there is no such subscription (HTTP 404)
            RateLimitedError: If the rate limit is hit (HTTP 429)
            ServerError: If the gateway fails (HTTP 5xx)
            HttpRequestError: If the answer cannot be read (the reason is its ``__cause__``)
            HttpClientError: If there is a network error
        """
        credentials = self._subscription_credentials()
        subscription = check_subscription_id(subscription_id)

        return await self._http_client.get(
            f"/v1/company/{self._company_id}/subscriptions/{subscription}",
            response_model=SubscriptionDetails,
            headers=credentials,
        )

    async def list_subscriptions(
        self,
        *,
        status: Optional[Union[SubscriptionStatus, str, Iterable[Union[SubscriptionStatus, str]]]] = None,
        billing_interval: Optional[Union[BillingInterval, str, Iterable[Union[BillingInterval, str]]]] = None,
        search: Optional[str] = None,
        created_from: Optional[Union[date, datetime]] = None,
        created_to: Optional[Union[date, datetime]] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SubscriptionPage:
        """
        List the subscriptions of the company, one page at a time.

        The client must be created with ``company_id`` and ``api_key``. Reading works even when subscriptions are
        switched off for the company. The call is not retried. To read all pages, call it again with a larger
        ``offset`` until ``offset + len(items) >= total``.

        Args:
            status: Only subscriptions in this status; one value or several (any of them matches)
            billing_interval: Only subscriptions charged at this interval; one value or several
            search: Matched against the customer's email, your reference and the subscription ID
            created_from: Only subscriptions created on or after this day or moment (a ``date``, or a ``datetime``
                with a timezone; moments are sent to the second)
            created_to: Only subscriptions created on or before this day or moment
            sort_by: ``created_at`` (the default), ``next_charge_at``, ``last_charged_at``, ``amount`` or ``status``
            sort_order: ``asc`` or ``desc``
            limit: Subscriptions per page, 1 to 100
            offset: How many matching subscriptions to skip

        Returns:
            SubscriptionPage with ``items``, ``total``, ``limit`` (the page size) and ``offset``

        Raises:
            ConfigurationError: Client configuration errors, e.g. the client has no ``company_id`` or ``api_key``
            ValueError: Input validation errors, e.g. ``limit`` is not from 1 to 100
            UnauthorizedError: If the API key is unknown (HTTP 401)
            ForbiddenError: If the API key belongs to another company (HTTP 403)
            RateLimitedError: If the rate limit is hit (HTTP 429)
            ServerError: If the gateway fails (HTTP 5xx)
            HttpRequestError: If the answer cannot be read (the reason is its ``__cause__``)
            HttpClientError: If there is a network error
        """
        credentials = self._subscription_credentials()
        query = SubscriptionListQuery.from_arguments(
            status=status,
            billing_interval=billing_interval,
            search=search,
            created_from=created_from,
            created_to=created_to,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

        response = await self._http_client.get(
            f"/v1/company/{self._company_id}/subscriptions",
            response_model=SubscriptionListResponse,
            headers=credentials,
            params=query.to_params(),
        )
        return SubscriptionPage(items=response.items, total=response.total, limit=response.page_size, offset=query.offset)

    async def _change_subscription(self, action: str, subscription_id: Union[UUID, str]) -> None:
        credentials = self._subscription_credentials()
        subscription = check_subscription_id(subscription_id)

        await self._http_client.patch(
            f"/v1/company/{self._company_id}/subscriptions/{subscription}/{action}",
            headers=credentials,
        )

    async def pause_subscription(self, subscription_id: Union[UUID, str]) -> None:
        """
        Pause an active subscription: no charges are made until it is resumed.

        The client must be created with ``company_id`` and ``api_key``. The next charge date is kept, so if it passes
        while the subscription is paused, the charge is attempted soon after it is resumed. The call is not
        retried: if the network fails you cannot tell whether the change was made, so read the subscription with
        ``get_subscription`` before repeating it.

        Args:
            subscription_id: The ID of the subscription, as a ``UUID`` or a string holding one

        Raises:
            ConfigurationError: Client configuration errors, e.g. the client has no ``company_id`` or ``api_key``
            ValueError: Input validation errors, e.g. ``subscription_id`` is not a UUID
            UnauthorizedError: If the API key is unknown (HTTP 401)
            ForbiddenError: If the API key or the subscription belongs to another company (HTTP 403)
            NotFoundError: If there is no such subscription (HTTP 404)
            ConflictError: If subscriptions are off for the company or the subscription is not active (HTTP 409)
            RateLimitedError: If the rate limit is hit (HTTP 429)
            ServerError: If the gateway fails (HTTP 5xx)
            HttpClientError: If there is a network error
        """
        await self._change_subscription("pause", subscription_id)

    async def resume_subscription(self, subscription_id: Union[UUID, str]) -> None:
        """
        Resume a paused subscription: scheduled charges go on.

        The client must be created with ``company_id`` and ``api_key``. The next charge date is not moved; if it has
        passed during the pause, the charge is attempted soon after the resume. The call is not retried (see
        ``pause_subscription``).

        Args:
            subscription_id: The ID of the subscription, as a ``UUID`` or a string holding one

        Raises:
            ConfigurationError: Client configuration errors, e.g. the client has no ``company_id`` or ``api_key``
            ValueError: Input validation errors, e.g. ``subscription_id`` is not a UUID
            UnauthorizedError: If the API key is unknown (HTTP 401)
            ForbiddenError: If the API key or the subscription belongs to another company (HTTP 403)
            NotFoundError: If there is no such subscription (HTTP 404)
            ConflictError: If subscriptions are off for the company or the subscription is not paused (HTTP 409)
            RateLimitedError: If the rate limit is hit (HTTP 429)
            ServerError: If the gateway fails (HTTP 5xx)
            HttpClientError: If there is a network error
        """
        await self._change_subscription("resume", subscription_id)

    async def cancel_subscription(self, subscription_id: Union[UUID, str]) -> None:
        """
        Cancel a subscription for good: no further charges, and it cannot be resumed.

        The client must be created with ``company_id`` and ``api_key``. Cancelling does not refund anything already
        charged; use ``refund_session`` with the ``payment_session_id`` of a charge in the history for that. The card
        is released when no other live subscription uses it. The call is not retried (see ``pause_subscription``).

        Args:
            subscription_id: The ID of the subscription, as a ``UUID`` or a string holding one

        Raises:
            ConfigurationError: Client configuration errors, e.g. the client has no ``company_id`` or ``api_key``
            ValueError: Input validation errors, e.g. ``subscription_id`` is not a UUID
            UnauthorizedError: If the API key is unknown (HTTP 401)
            ForbiddenError: If the API key or the subscription belongs to another company (HTTP 403)
            NotFoundError: If there is no such subscription (HTTP 404)
            ConflictError: If subscriptions are off for the company or the subscription is already cancelled (HTTP 409)
            RateLimitedError: If the rate limit is hit (HTTP 429)
            ServerError: If the gateway fails (HTTP 5xx)
            HttpClientError: If there is a network error
        """
        await self._change_subscription("cancel", subscription_id)

    @staticmethod
    def parse_payment_callback(payload: str, secret_key: Optional[str] = None) -> PaymentCallback:
        """
        Parse and validate a payment callback from the gateway.

        Supports both callback formats:
        - Legacy (generic): fields {order_id, total, currency, success, tx_id, tx_meta, datetime, signature}
          Signature over: order_id|total|success
        - Schema 1.1 (generic_signed): fields {type, status, schema, order_id, session_id, event_id, ...}
          Signature over: type|status|order_id|amount|currency

        The format is auto-detected by the presence of the "schema" field in the payload.

        Args:
            payload: JSON string containing the payment callback data
            secret_key: Optional secret key for signature verification

        Returns:
            PaymentCallback object with parsed data

        Raises:
            AssertionError: If signature verification fails
        """
        import json

        raw = json.loads(payload)

        if "schema" in raw:
            data = SignedPaymentCallbackRaw.from_dict(raw)
            if secret_key:
                amount = data.total if data.total is not None else data.refunded_amount
                AsyncPolakoClient._verify_signature(
                    f"{data.type}|{data.status}|{data.order_id}|{amount}|{data.currency}",
                    secret_key,
                    data.signature,
                )
            return data.to_callback()
        else:
            data = PaymentCallbackRaw.from_dict(raw)
            if secret_key:
                AsyncPolakoClient._verify_signature(
                    f"{data.order_id}|{data.total}|{data.success}",
                    secret_key,
                    data.signature,
                )
            return data.to_callback()

    @staticmethod
    def _create_signature(source_str: str, secret_key: str) -> str:
        """Create HMAC-SHA256 signature for request authentication."""
        import hashlib
        import hmac

        return hmac.new(secret_key.encode(), source_str.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _verify_signature(source_str: str, secret_key: str, expected_sig: str) -> None:
        """
        Verify HMAC-SHA256 signature.

        Raises:
            AssertionError: If signature doesn't match
        """
        import hmac

        if not hmac.compare_digest(AsyncPolakoClient._create_signature(source_str, secret_key), expected_sig):
            raise AssertionError("The signature doesn't match.")
