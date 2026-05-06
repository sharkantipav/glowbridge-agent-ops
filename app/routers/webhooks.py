"""Public webhook endpoints — Stripe, etc. NO bearer auth (Stripe verifies via signature)."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from app.agents import customer
from app.integrations import stripe_wh

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="missing stripe-signature header")
    payload = await request.body()
    try:
        event = stripe_wh.verify_webhook(payload, stripe_signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"signature verification failed: {e}") from e

    # Only act on the $199 setup payment for now.
    if stripe_wh.is_setup_payment(event):
        result = customer.handle_setup_payment(event)
        return {"received": True, "handled": True, **result}

    return {"received": True, "handled": False, "type": event.get("type")}
