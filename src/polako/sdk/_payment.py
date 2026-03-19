"""Payment initiation models for direct payment flow."""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

from polako.sdk._serializable import Serializable


@dataclass
class PaymentInitRequest(Serializable):
    """
    Request payload for initiating payment on an existing session.

    Maps to the backend's PaymentSessionInitData model
    at POST /api/session/{session_id}/payment_url.

    Attributes:
        payment_option_id: UUID of the selected payment option/provider
        customer: Customer info dict (must include first_name, last_name, email)
        language_code: Language code for the payment page (sr, en, ru)
        terms_accepted: Whether the customer accepted terms of service
        address_shipping: Optional shipping address dict
        sec_data: Optional reCAPTCHA data (None when platform has skip_recaptcha enabled)
    """

    payment_option_id: UUID
    customer: Dict[str, Any]
    language_code: str
    terms_accepted: bool
    address_shipping: Optional[Dict[str, Any]]
    sec_data: None


@dataclass
class PaymentResult(Serializable):
    """
    Response from the payment initiation endpoint.

    Field names use camelCase to match the backend's JSON alias serialization.

    Attributes:
        sessionId: Payment session UUID as string
        type: Payment gateway type — "redirect" or "form-data"
        paymentUrl: URL to redirect customer to for payment completion
        metadata: Optional provider-specific metadata
    """

    sessionId: str
    type: Optional[str]
    paymentUrl: Optional[str]
    metadata: Optional[Dict[str, Any]]
