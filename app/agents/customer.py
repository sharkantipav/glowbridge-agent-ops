"""Customer agent — onboard a paid setup customer.

Triggered by Stripe webhook (checkout.session.completed for the $199 setup):
  1. Create or update `customers` row (status=pending_setup -> awaiting_test_call).
  2. Send welcome email with setup-form link.
  3. Generate a draft AI receptionist call flow tailored to the company.
  4. Create an `approvals` row of kind 'customer_action' so Charles approves
     the call flow before it's used live.
"""
from __future__ import annotations

from app import db, llm
from app.agents.base import run_context
from app.config import get_settings

WELCOME_SUBJECT = "Welcome to GlowBridge — next steps for your test call"

WELCOME_BODY_TEMPLATE = """\
Hi {first_name},

Thanks for joining the GlowBridge Founding Pilot — really glad to have you.

Two quick steps to get your AI receptionist running:

1. Fill out the short setup form: {setup_form_url}
   (Takes about 5 minutes — services you offer, hours, areas you cover.)

2. Once that's in, I'll send you a link to do a free test call. If you're
   not comfortable going live after the test call, your $199 setup fee is
   refunded — no questions.

Reply to this email with any questions.

— Charles
GlowBridge
"""

CALL_FLOW_SYSTEM = """\
You are designing a draft call-handling flow for an AI receptionist that will
answer missed and after-hours calls for a small pest control company.

Given the company's name, location, and any context, return a JSON object:
{
  "greeting": string (one short sentence the AI says when picking up),
  "questions": [string, ...]  (3-6 fields the AI must capture),
  "boundaries": [string, ...]  (things the AI must NEVER do or say),
  "handoff_method": "sms"|"email"|"both",
  "handoff_template": string (the message texted/emailed to the owner),
  "after_hours_note": string (what the AI says outside business hours)
}

Hard rules — encode these in the boundaries:
- The AI MUST NOT quote pest-control prices.
- The AI MUST NOT guarantee a service appointment, pricing, or outcome.
- The AI MUST NOT diagnose the pest issue.
- If the caller is in distress (e.g. severe infestation, allergic reaction,
  rodent in baby's room), promise prompt callback within 30 minutes during
  business hours, otherwise first thing next business day.
"""


def _draft_call_flow(company_name: str, city: str | None, state: str | None) -> dict:
    user = (
        f"Company: {company_name}\n"
        f"Location: {city or '?'}, {state or '?'}\n"
        f"Draft the flow."
    )
    try:
        return llm.json_call(
            system=CALL_FLOW_SYSTEM,
            user=user,
            tier="smart",
            temperature=0.3,
            max_tokens=900,
        )
    except Exception:
        return {}


def _send_welcome(to: str, first_name: str, setup_form_url: str) -> str | None:
    try:
        from app.integrations import gmail
        body = WELCOME_BODY_TEMPLATE.format(first_name=first_name or "there", setup_form_url=setup_form_url)
        return gmail.send_email(to=to, subject=WELCOME_SUBJECT, body=body)
    except Exception:
        return None


def handle_setup_payment(stripe_event: dict) -> dict:
    """Run the onboarding for a single Stripe setup-payment event."""
    s = get_settings()
    session = stripe_event["data"]["object"]
    customer_email = session.get("customer_details", {}).get("email") or session.get("customer_email")
    customer_phone = session.get("customer_details", {}).get("phone")
    company_name = (
        session.get("custom_fields", [{}])[0].get("text", {}).get("value")
        if session.get("custom_fields")
        else None
    ) or session.get("metadata", {}).get("company_name") or "your company"
    stripe_customer_id = session.get("customer")
    payment_id = session.get("payment_intent") or session.get("id")

    with run_context("customer", {"stripe_event_id": stripe_event.get("id")}) as run:
        # Find existing customer by stripe id, or create new
        existing = db.select("customers", stripe_customer_id=stripe_customer_id) if stripe_customer_id else []
        if existing:
            customer = existing[0]
            db.update(
                "customers",
                customer["id"],
                {
                    "status": "awaiting_test_call",
                    "stripe_setup_payment_id": payment_id,
                    "setup_paid_at": "now()",
                },
            )
        else:
            customer = db.insert(
                "customers",
                {
                    "company_name": company_name,
                    "contact_email": customer_email,
                    "contact_phone": customer_phone,
                    "stripe_customer_id": stripe_customer_id,
                    "stripe_setup_payment_id": payment_id,
                    "setup_paid_at": "now()",
                    "status": "awaiting_test_call",
                },
            )

        setup_form_url = f"{s.app_base_url}/setup/{customer['id']}"
        first_name = (customer_email or "there").split("@")[0].split(".")[0].title()
        gmail_msg_id = _send_welcome(customer_email, first_name, setup_form_url)
        if gmail_msg_id:
            run.info("welcome_sent", customer_id=customer["id"], gmail_id=gmail_msg_id)
        else:
            run.warn("welcome_send_failed", customer_id=customer["id"])

        flow = _draft_call_flow(company_name, customer.get("city"), customer.get("state"))
        db.update("customers", customer["id"], {"call_flow_draft": flow, "setup_form_url": setup_form_url})
        run.info("call_flow_drafted", customer_id=customer["id"], flow_keys=list(flow.keys()))

        # Approval queue: human signs off on the flow before it's used live.
        db.insert(
            "approvals",
            {
                "kind": "customer_action",
                "target_id": customer["id"],
                "payload": {
                    "company_name": company_name,
                    "contact_email": customer_email,
                    "call_flow": flow,
                    "setup_form_url": setup_form_url,
                },
                "reason_for_review": "approve_call_flow_for_test_call",
            },
        )

        run.output = {"customer_id": customer["id"], "welcome_sent": bool(gmail_msg_id)}
        return run.output
