from fastapi import APIRouter, HTTPException, Request

from app.agents.customer_agent import CustomerAgent
from app.agents.outreach_agent import OutreachAgent
from app.agents.reply_agent import ReplyAgent
from app.integrations.gmail_client import GmailClient
from app.integrations.stripe_handler import parse_event
from app.services.repository import Repository

router = APIRouter()
repo = Repository()
gmail = GmailClient()


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = parse_event(payload, sig)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        company_name = obj.get("customer_details", {}).get("name", "New Customer")
        flow = CustomerAgent().draft_call_flow(company_name)
        repo.log_event("customer", "onboarded", {"company": company_name, "flow": flow})
    return {"received": True}


@router.post("/ops/outreach")
def run_outreach(lead: dict):
    agent = OutreachAgent()
    email = agent.draft_email(lead)
    allowed, reason = agent.can_auto_send(lead, email)
    if allowed:
        gmail.send_email(lead["email"], "Missed calls after-hours?", email)
        repo.log_event("outreach", "email_sent", {"lead": lead, "email": email})
        return {"status": "sent", "email": email}
    repo.pending_approval("outreach_email", {"lead": lead, "email": email}, reason)
    return {"status": "pending_approval", "reason": reason, "email": email}


@router.post("/ops/reply/classify")
def classify_reply(payload: dict):
    label = ReplyAgent().classify(payload.get("body", ""))
    should_escalate = label in ReplyAgent.ESCALATE
    repo.log_event("reply", "classified", {"label": label, "payload": payload})
    return {"label": label, "escalate": should_escalate}
