"""Async API client for Polako Finance."""

from decimal import Decimal
from typing import Optional, TypeVar
from uuid import UUID

from polako.sdk._async_client import AsyncHttpClient
from polako.sdk._exceptions import HttpClientError, HttpRequestError, PaymentInitError
from polako.sdk._order import (
    CreateOrderRequest,
    CustomerAddress,
    CustomerInfo,
    OrderDetails,
    PaymentCallback,
    PaymentCallbackRaw,
    SessionInfo,
)
from polako.sdk._payment import PaymentInitRequest, PaymentResult

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
            "/api/session/signed",
            request_body=request,
            response_model=SessionInfo,
        )

    @staticmethod
    def parse_payment_callback(payload: str, secret_key: Optional[str] = None) -> PaymentCallback:
        """
        Parse and validate a payment callback from the gateway.

        Args:
            payload: JSON string containing the payment callback data
            secret_key: Optional secret key for signature verification

        Returns:
            PaymentCallback object with parsed data

        Raises:
            AssertionError: If signature verification fails
        """
        data = PaymentCallbackRaw.from_json(payload)

        if secret_key:
            AsyncPolakoClient._verify_signature(
                f"{data.order_id}|{data.total}|{data.success}",
                secret_key,
                data.signature,
            )

        return data.to_callback()

    async def create_order_with_payment(
        self,
        order: OrderDetails,
        customer: CustomerInfo,
        payment_option_id: UUID,
        platform_id: UUID,
        secret_key: str,
        terms_accepted: bool = True,
        address_shipping: Optional[CustomerAddress] = None,
    ) -> tuple[SessionInfo, PaymentResult]:
        """
        Create an order and immediately initiate payment in a single flow.

        Requires the platform to have skip_recaptcha enabled in its payment config.
        Your integration handles UI validation and terms acceptance before calling this.

        Args:
            order: Order details containing items, totals, and metadata
            customer: Customer information (first_name, last_name, email are required)
            payment_option_id: UUID of the selected payment option/provider
            platform_id: Platform identifier UUID for authentication
            secret_key: Secret key used for generating request signature
            terms_accepted: Whether customer accepted terms (default: True)
            address_shipping: Optional shipping address

        Returns:
            Tuple of (SessionInfo, PaymentResult) — session details and payment URL

        Raises:
            ValueError: If validation of order or customer fails
            HttpRequestError: If session creation (step 1) fails
            PaymentInitError: If payment initiation (step 2) fails;
                carries session_info so you can retry
            HttpClientError: If there's a network error
        """
        # Validate customer has required fields for payment initiation
        customer.validate_for_payment()
        order.validate()

        # Step 1: Create session
        session = await self.create_order(order, customer, platform_id, secret_key)

        # Step 2: Initiate payment
        language = order.language or "sr"

        payment_request = PaymentInitRequest(
            payment_option_id=payment_option_id,
            customer=customer.to_dict(),
            language_code=language,
            terms_accepted=terms_accepted,
            address_shipping=address_shipping.to_dict() if address_shipping else None,
            sec_data=None,
        )

        try:
            payment_result = await self._http_client.post(
                f"/api/session/{session.paymentSessionId}/payment_url",
                request_body=payment_request,
                response_model=PaymentResult,
            )
        except (HttpRequestError, HttpClientError) as e:
            raise PaymentInitError(
                message=f"Payment initiation failed: {e.message}",
                session_info=session,
                status_code=getattr(e, "status_code", None),
                response_body=getattr(e, "response_body", None),
            ) from e

        return session, payment_result

    async def get_payment_url(
        self,
        order: OrderDetails,
        customer: CustomerInfo,
        payment_option_id: UUID,
        platform_id: UUID,
        secret_key: str,
        terms_accepted: bool = True,
        address_shipping: Optional[CustomerAddress] = None,
    ) -> str:
        """
        Create an order and get the payment URL in one call.

        Convenience wrapper around create_order_with_payment that returns
        only the payment URL string.

        Args:
            order: Order details containing items, totals, and metadata
            customer: Customer information (first_name, last_name, email are required)
            payment_option_id: UUID of the selected payment option/provider
            platform_id: Platform identifier UUID for authentication
            secret_key: Secret key used for generating request signature
            terms_accepted: Whether customer accepted terms (default: True)
            address_shipping: Optional shipping address

        Returns:
            Payment URL string to redirect the customer to

        Raises:
            ValueError: If validation fails or payment URL is not available
            HttpRequestError: If session creation fails
            PaymentInitError: If payment initiation fails
            HttpClientError: If there's a network error
        """
        _, payment = await self.create_order_with_payment(
            order=order,
            customer=customer,
            payment_option_id=payment_option_id,
            platform_id=platform_id,
            secret_key=secret_key,
            terms_accepted=terms_accepted,
            address_shipping=address_shipping,
        )

        if not payment.paymentUrl:
            raise ValueError("Payment URL not available in response")

        return payment.paymentUrl

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
