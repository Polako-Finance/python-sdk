"""Async API client for Polako Finance."""

from decimal import Decimal
from typing import List, Optional, TypeVar
from uuid import UUID

from polako.sdk._async_client import AsyncHttpClient
from polako.sdk._order import (
    CreateOrderRequest,
    CustomerAddress,
    CustomerInfo,
    InitCustomerInfo,
    OrderDetails,
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
    ):
        """
        Initialize the async Polako Finance client.

        Args:
            timeout: Request timeout in seconds (default: 30.0)
            test_env: If True, use test environment URL; otherwise use production (default: False)
        """
        from polako.sdk._constants import BASE_URL_PROD, BASE_URL_TEST

        self._http_client = AsyncHttpClient(
            base_url=BASE_URL_TEST if test_env else BASE_URL_PROD,
            timeout=timeout,
        )

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

        from polako.sdk._constants import CURRENCIES, LANGUAGES

        # Prepare values
        currency = order.currency or next(iter(CURRENCIES))
        language = order.language or next(iter(LANGUAGES))
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
