"""Example of handling payment callbacks from Polako Finance."""

import hashlib
import hmac
import json

from polako.sdk import PolakoClient

# Your secret key (replace with actual value)
SECRET_KEY = "your-secret-key-here"

# Example callback payload (this would come from your webhook endpoint)
_BODY = {
    "order_id": "ORDER-12345",
    "total": "250.00",
    "currency": "RSD",
    "success": 1,
    "tx_id": "TX-ABC123",
    "tx_meta": {"payment_method": "card", "card_type": "visa"},
    "datetime": "2024-11-02 14:30",
}
# The gateway signs every callback; here we sign the example the same way so it passes verification
_BODY["signature"] = hmac.new(
    SECRET_KEY.encode(), f"{_BODY['order_id']}|{_BODY['total']}|{_BODY['success']}".encode(), hashlib.sha256
).hexdigest()
CALLBACK_PAYLOAD = json.dumps(_BODY)


def handle_payment_callback(payload: str, secret_key: str):
    """
    Handle payment callback from Polako Finance.

    Args:
        payload: JSON string from the webhook
        secret_key: Your secret key, used to verify the callback signature
    """
    try:
        # Parse the callback and verify its signature
        callback = PolakoClient.parse_payment_callback(
            payload=payload,
            secret_key=secret_key,
        )

        print("Payment callback received:")
        print(f"Order ID: {callback.order_id}")
        print(f"Amount: {callback.total} {callback.currency}")
        print(f"Transaction ID: {callback.tx_id}")
        print(f"Success: {callback.success}")
        print(f"Timestamp: {callback.datetime}")
        print(f"Metadata: {callback.tx_meta}")

        if callback.success:
            print("\nPayment was successful!")
            # Update your database, fulfill the order, etc.
            process_successful_payment(callback)
        else:
            print("\nPayment failed!")
            # Handle failed payment
            process_failed_payment(callback)

    except AssertionError as e:
        print(f"Signature verification failed: {e}")
    except Exception as e:
        print(f"Error processing callback: {e}")


def process_successful_payment(callback):
    """Process a successful payment."""
    # TODO: Implement your business logic here
    # - Update order status in database
    # - Send confirmation email to customer
    # - Trigger fulfillment process
    # - Update inventory
    print(f"Processing successful payment for order {callback.order_id}")


def process_failed_payment(callback):
    """Process a failed payment."""
    # TODO: Implement your business logic here
    # - Update order status in database
    # - Notify customer of failed payment
    # - Log the failure for analysis
    print(f"Processing failed payment for order {callback.order_id}")


if __name__ == "__main__":
    print("Example: with signature verification")
    print("-" * 50)
    handle_payment_callback(CALLBACK_PAYLOAD, SECRET_KEY)
