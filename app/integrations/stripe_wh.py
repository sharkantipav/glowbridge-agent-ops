"""Stripe webhook verification + helpers."""
from __future__ import annotations

from typing import Any

import stripe

from app.config import get_settings


def init_stripe() -> None:
    s = get_settings()
    if s.stripe_secret_key:
        stripe.api_key = s.stripe_secret_key


def verify_webhook(payload: bytes, sig_header: str) -> dict[str, Any]:
    """Verify a Stripe webhook signature and return the parsed event dict.

    Raises stripe.error.SignatureVerificationError on tampering.
    """
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not set")
    event = stripe.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
    return event  # stripe.Event acts like a dict


def is_setup_payment(event: dict[str, Any]) -> bool:
    """True if the event represents a successful $199 setup-fee payment."""
    s = get_settings()
    if event["type"] != "checkout.session.completed":
        return False
    session = event["data"]["object"]
    # If a setup price ID is configured, match against it; otherwise accept any one-time payment.
    if s.stripe_price_setup:
        line_items = session.get("line_items", {}).get("data", []) or []
        if not line_items:
            return False
        return any(li.get("price", {}).get("id") == s.stripe_price_setup for li in line_items)
    return session.get("mode") == "payment" and session.get("payment_status") == "paid"
