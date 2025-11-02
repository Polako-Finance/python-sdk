"""Example of using the Polako Finance client."""

import asyncio
from decimal import Decimal
from uuid import UUID

from polako.sdk import PolakoClient, CustomerInfo, OrderDetails, OrderItem


async def create_payment_session():
    """Create a payment session using the client."""
    # Use async context manager for automatic resource cleanup
    async with PolakoClient(test_env=True, timeout=30.0) as client:
        # Create order items
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

        # Create order details
        order = OrderDetails(
            currency="RSD",
            language="en",
            order_id="ORDER-67890",
            items=items,
            total=Decimal("50.00"),
        )

        # Create customer information
        customer = CustomerInfo(
            first_name="Jane",
            last_name="Smith",
            email="jane.smith@example.com",
            phone="+381987654321",
            address=None,
        )

        # Your platform credentials (replace with actual values)
        PLATFORM_ID = UUID("00000000-0000-0000-0000-000000000000")  # Replace with your platform ID
        SECRET_KEY = "your-secret-key-here"  # Replace with your secret key

        try:
            # Create payment session
            session = await client.create_order(
                order=order,
                customer=customer,
                platform_id=PLATFORM_ID,
                secret_key=SECRET_KEY,
            )

            print("Payment session created successfully!")
            print(f"Session ID: {session.paymentSessionId}")
            print(f"Payment URL: {session.paymentPageUrl}")
            print(f"Expires at: {session.expiresAt}")
            print("\nRedirect the customer to the payment URL to complete the payment.")

            return session

        except ValueError as e:
            print(f"Validation error: {e}")
        except Exception as e:
            print(f"Error creating payment session: {e}")


async def main():
    """Main async function."""
    await create_payment_session()


if __name__ == "__main__":
    # Run the async function
    asyncio.run(main())
