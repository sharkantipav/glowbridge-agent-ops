"""Public webhook endpoints — Stripe, Vapi. NO bearer auth (signatures verify)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app import db, llm
from app.agents import customer
from app.config import get_settings
from app.integrations import stripe_wh
from app.logging_setup import get_logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger("webhooks")


# ---------- Stripe ----------

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


# ---------- Vapi ----------

LEAD_HANDOFF_SYSTEM = """\
You write a single short email to a pest control owner summarizing a call their AI
receptionist just took. The email must include, in clear bullet form when present:
  - Caller name
  - Callback number
  - City / address
  - Pest issue described
  - Urgency (and any distress flag)
  - Preferred callback time
  - One-sentence summary of the call

Plain text only. No "guaranteed", no pricing, no diagnosis. Keep under 120 words.
End with: "Full transcript available in your GlowBridge dashboard."

Reply ONLY with JSON: { "subject": string, "body": string }
"""


def _extract_lead(transcript: str) -> dict[str, Any]:
    """Use Claude to pull structured lead data + a handoff email from a transcript."""
    if not transcript or len(transcript.strip()) < 30:
        return {"subject": "GlowBridge — short or empty call",
                "body": "A call came in but no useful info was captured."}
    try:
        return llm.json_call(
            system=LEAD_HANDOFF_SYSTEM,
            user=f"Transcript:\n{transcript[:8000]}",
            tier="fast",
            max_tokens=500,
        )
    except Exception as e:
        return {"subject": "GlowBridge — call received (parse failed)",
                "body": f"A call came in. Couldn't auto-summarize ({e}). See dashboard for full transcript."}


def _send_handoff(customer_row: dict, subject: str, body: str) -> bool:
    from app.integrations import gmail
    try:
        gmail.send_email(to=customer_row["contact_email"], subject=subject, body=body)
        return True
    except Exception as e:
        log.error("handoff_email_failed", customer_id=customer_row.get("id"), error=str(e))
        return False


@router.post("/vapi")
async def vapi_webhook(request: Request, x_vapi_signature: str | None = Header(None)):
    """Vapi POSTs here on call lifecycle events (status updates + end-of-call report).

    We act on the end-of-call event: persist the call, draft a handoff email
    summarizing the lead, send it to the customer's contact_email.

    Vapi event shapes vary slightly by version; this handler is defensive.
    """
    s = get_settings()
    raw = await request.body()

    # Optional signature verification
    if s.vapi_webhook_secret:
        if not x_vapi_signature or x_vapi_signature != s.vapi_webhook_secret:
            log.warning("vapi_webhook_bad_signature")
            raise HTTPException(status_code=403, detail="invalid Vapi signature")

    try:
        event: dict[str, Any] = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")  # noqa: B904

    msg = event.get("message") or event  # Vapi nests payload under 'message'
    event_type = msg.get("type") or event.get("type")

    if event_type not in {"end-of-call-report", "call.ended", "status-update"}:
        # Fast-path: log and ack everything else (we only act on call end).
        log.info("vapi_event_ignored", type=event_type)
        return {"received": True, "handled": False, "type": event_type}

    call = msg.get("call") or {}
    assistant_id = call.get("assistantId") or msg.get("assistantId")
    vapi_call_id = call.get("id") or msg.get("callId")
    transcript = msg.get("transcript") or call.get("transcript") or ""
    summary = msg.get("summary") or msg.get("analysis", {}).get("summary")
    structured = msg.get("structuredData") or msg.get("analysis", {}).get("structuredData") or {}
    duration = msg.get("durationSeconds") or call.get("duration")
    cost = msg.get("cost") or call.get("cost")
    caller_phone = (call.get("customer") or {}).get("number")

    # Match to a customer by assistant id
    customer_rows = db.select("customers", vapi_assistant_id=assistant_id) if assistant_id else []
    customer_row = customer_rows[0] if customer_rows else None

    # Persist the call
    call_row = {
        "customer_id": customer_row["id"] if customer_row else None,
        "vapi_call_id": vapi_call_id,
        "vapi_assistant_id": assistant_id,
        "caller_phone": caller_phone,
        "status": "ended",
        "ended_at": "now()",
        "duration_sec": int(duration) if duration else None,
        "transcript": transcript,
        "summary": summary,
        "structured_data": structured,
        "cost_usd": cost,
        "raw_payload": event,
    }
    try:
        db.insert("calls", call_row)
    except Exception as e:
        log.error("call_insert_failed", error=str(e), vapi_call_id=vapi_call_id)

    # Lead handoff email — only if we have a customer to deliver to
    handoff_sent = False
    if customer_row:
        if not summary and transcript:
            extracted = _extract_lead(transcript)
            subject = extracted.get("subject") or f"New lead via GlowBridge — {customer_row['company_name']}"
            body = extracted.get("body") or transcript[:1000]
        else:
            subject = f"New lead via GlowBridge — {customer_row['company_name']}"
            body = summary or transcript[:1500] or "Empty transcript."
        handoff_sent = _send_handoff(customer_row, subject, body)

    log.info(
        "vapi_call_ended",
        assistant_id=assistant_id,
        vapi_call_id=vapi_call_id,
        duration=duration,
        handoff_sent=handoff_sent,
        matched_customer=bool(customer_row),
    )
    return {"received": True, "handled": True, "handoff_sent": handoff_sent}
