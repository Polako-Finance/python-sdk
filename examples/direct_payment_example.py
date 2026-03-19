"""Example of using direct payment initiation (single-call flow).

This flow bypasses the standard two-step process where the customer
visits the payment page. Instead, your integration handles UI validation
and terms acceptance, then calls the SDK to get the payment URL directly.

Prerequisites:
    - Your platform must have skip_recaptcha enabled in its payment_config.
    - You must know the payment_option_id for the desired payment method.
"""

import asyncio
from decimal import Decimal
from uuid import UUID

from polako.sdk import (
    PolakoClient,
    CustomerAddress,
    CustomerInfo,
    OrderDetails,
    OrderItem,
    PaymentInitError,
    PaymentResult,
)


async def direct_payment():
    """Create an order and get the payment URL in a single call."""
    async with PolakoClient(test_env=True, timeout=30.0) as client:
        items = [
            OrderItem(
                code="PROD-001",
                name="Digital Service",
                description="Monthly subscription",
                price=Decimal("50.00"),
                quantity=1,
                tax="VAT",
            ),
        ]

        order = OrderDetails(
            currency="RSD",
            language="en",
            order_id="ORDER-12345",
            items=items,
            total=Decimal("50.00"),
        )

        # first_name, last_name, email are required for direct payment
        customer = CustomerInfo(
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
            phone="+381987654321",
            address=CustomerAddress(
                address="123 Main St",
                city="Belgrade",
                state=None,
                zip="11000",
                country="RS",
            ),
        )

        # Replace with your actual credentials
        PLATFORM_ID = UUID("00000000-0000-0000-0000-000000000000")
        SECRET_KEY = "your-secret-key-here"
        PAYMENT_OPTION_ID = UUID("00000000-0000-0000-0000-000000000001")

        try:
            # Option A: Get both session and payment result
            session, payment = await client.create_order_with_payment(
                order=order,
                customer=customer,
                payment_option_id=PAYMENT_OPTION_ID,
                platform_id=PLATFORM_ID,
                secret_key=SECRET_KEY,
            )

            print(f"Session ID: {session.paymentSessionId}")
            print(f"Payment URL: {payment.paymentUrl}")
            print(f"Payment type: {payment.type}")

            # Option B: Get just the payment URL
            # payment_url = await client.get_payment_url(
            #     order=order,
            #     customer=customer,
            #     payment_option_id=PAYMENT_OPTION_ID,
            #     platform_id=PLATFORM_ID,
            #     secret_key=SECRET_KEY,
            # )
            # print(f"Redirect to: {payment_url}")

        except PaymentInitError as e:
            # Session was created but payment initiation failed.
            # You can retry using the session info.
            print(f"Payment initiation failed: {e.message}")
            print(f"Session was created: {e.session_info.paymentSessionId}")
            print(f"HTTP status: {e.status_code}")

        except ValueError as e:
            print(f"Validation error: {e}")

        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(direct_payment())
