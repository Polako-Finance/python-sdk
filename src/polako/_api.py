from decimal import Decimal
from typing import Optional, TypeVar
from uuid import UUID

from polako._client import HttpClient
from polako._order import CustomerInfo, OrderDetails, PaymentCallback, PaymentCallbackRaw, SessionInfo

T = TypeVar("T")


class PolakoClient:
    """
    Main SDK client for the Polako Finance payment gateway.

    This client provides a high-level interface to interact with the payment gateway API.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        test_env: bool = False,
    ):
        """
        Initialize the Polako Finance client.

        Args:
            timeout: Request timeout in seconds (default: 30.0)
            test_env: If True, use test environment URL; otherwise use production (default: False)
        """
        from polako._constants import BASE_URL_PROD, BASE_URL_TEST

        self._http_client = HttpClient(
            base_url=BASE_URL_TEST if test_env else BASE_URL_PROD,
            timeout=timeout,
        )

    def create_order(
        self,
        order: OrderDetails,
        customer: CustomerInfo,
        platform_id: UUID,
        secret_key: str,
    ) -> SessionInfo:
        """
        Create a new order in the payment gateway.

        Args:
            order: Order details containing items, totals, and metadata
            customer: Customer information including contact and address details
            platform_id: Platform identifier UUID for authentication
            secret_key: Secret key used for generating request signature

        Returns:
            Deserialized response model instance

        Raises:
            ValueError: If validation of order or customer fails
            HttpRequestError: If the API request fails
            HttpClientError: If there's a network error
        """
        # Validate both arguments before sending request
        order.validate()
        customer.validate()

        from polako._constants import CURRENCIES, LANGUAGES

        payload = {
            "platform_id": platform_id,
            "currency": order.currency or next(iter(CURRENCIES)),
            "language": order.language or next(iter(LANGUAGES)),
            "order_id": order.order_id,
            "customer": customer.to_dict(),
            "items": [item.to_dict() for item in order.items],
            "total": order.total.quantize(Decimal("0.01")),
            "response": "object",
        }

        payload["signature"] = self._create_signature(
            f"{payload['order_id']}|{payload['total']:.2f}|{payload['currency']}",
            secret_key,
        )

        # Send POST request to create order
        return self._http_client.post(
            "/api/session/signed",
            request_body=payload,
            response_model=SessionInfo,
        )

    @staticmethod
    def parse_payment_callback(payload: str, secret_key: Optional[str]) -> PaymentCallback:
        data = PaymentCallbackRaw.from_json(payload)

        if secret_key:
            PolakoClient._verify_signature(
                f"{data.order_id}|{data.total}|{data.success}",
                secret_key,
                data.signature,
            )

        return data.to_callback()

    @staticmethod
    def _create_signature(source_str: str, secret_key: str) -> str:
        import hashlib
        import hmac

        return hmac.new(secret_key.encode(), source_str.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _verify_signature(source_str: str, secret_key: str, expected_sig: str):
        import hmac

        if not hmac.compare_digest(PolakoClient._create_signature(source_str, secret_key), expected_sig):
            raise AssertionError("The signature doesn't match.")
