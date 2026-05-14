"""Reply agent — classify Gmail replies and decide auto-reply vs escalate.

For the v1 vertical slice, this is structurally complete but defaults to
escalating everything. Auto-reply only fires for `asked_price` /
`asked_how_it_works` AND classifier confidence >= 0.85 AND
ENABLE_REPLY_AUTOREPLY=true.

Anything `interested`, `wants_call`, `angry`, `unsubscribe`, or `unknown`
goes straight to the approval queue with the parsed message attached.
"""
from __future__ import annotations

import re

from app import db, llm, safety
from app.agents.base import run_context
from app.config import get_settings

CLASSIFY_SYSTEM = """\
You classify replies to a cold outreach email. The original email offered
GlowBridge — an AI receptionist for pest control companies, $199 setup +
$99/month, free if not comfortable after a test call.

Classify the reply into ONE of:
  interested, not_interested, asked_price, asked_how_it_works,
  wants_call, objection, angry, unsubscribe, unknown

Rules:
- "How does it work?" / "Tell me more" → asked_how_it_works
- "How much?" / "What's the price?" → asked_price
- "Yes I'd like to see this" / "Send me details" → interested
- "Call me" / "What's your number" / "Let's hop on a call" → wants_call
- ANY anger, profanity, threats, legal references → angry
- "Stop", "Unsubscribe", "Remove me", "Don't email me" → unsubscribe
- Pushback that isn't anger ("Too expensive", "We tried this", "Not for us") → objection / not_interested
- Genuinely ambiguous or off-topic → unknown

Reply ONLY with JSON:
{ "intent": "<one_of_above>", "confidence": number 0-1, "rationale": string }
"""

AUTOREPLY_SYSTEM = """\
You are answering a cold-email reply on behalf of GlowBridge. The reply is asking
EITHER about the price OR about how it works. Answer in 60 words or less, plain text.

Pricing facts you may state:
- $199 one-time setup
- $99/month thereafter
- Setup fee is refunded if they aren't comfortable going live after a free test call

How-it-works facts:
- We forward your missed and after-hours calls to our AI receptionist
- It greets the caller, gathers name/phone/address/issue, and texts/emails the lead to you
- We do NOT quote pest-control prices to your customers
- We do NOT promise booking outcomes

NEVER:
- Quote a number of jobs, leads, or revenue
- Promise outcomes
- Say "guaranteed"

End with: "Want me to set up a 5-minute demo?"

Reply ONLY with JSON: { "body": string }
"""


def _classify(message: dict) -> dict:
    user = (
        f"From: {message.get('from_email')}\n"
        f"Subject: {message.get('subject')}\n"
        f"Body:\n{(message.get('body') or '')[:4000]}"
    )
    try:
        return llm.json_call(
            system=CLASSIFY_SYSTEM,
            user=user,
            tier="fast",
            temperature=0.1,
            max_tokens=200,
        )
    except Exception:
        return {"intent": "unknown", "confidence": 0.0, "rationale": "classifier_error"}


def _draft_autoreply(message: dict, intent: str) -> str | None:
    user = (
        f"Their reply (intent={intent}):\n{(message.get('body') or '')[:2000]}"
    )
    try:
        out = llm.json_call(
            system=AUTOREPLY_SYSTEM,
            user=user,
            tier="smart",
            temperature=0.3,
            max_tokens=300,
        )
        return out.get("body")
    except Exception:
        return None


def _record_reply(message: dict, intent: str, confidence: float,
                  auto_replied: bool, auto_reply_body: str | None,
                  escalated: bool) -> dict:
    return db.insert(
        "replies",
        {
            "from_email": message.get("from_email"),
            "subject": message.get("subject"),
            "body": message.get("body"),
            "intent": intent,
            "confidence": confidence,
            "auto_replied": auto_replied,
            "auto_reply_body": auto_reply_body,
            "escalated": escalated,
            "gmail_message_id": message.get("id"),
        },
    )


def _send_reply(to: str, subject: str, body: str, thread_id: str | None) -> str:
    from app.integrations import gmail
    reply_subject = subject if (subject or "").lower().startswith("re:") else f"Re: {subject or ''}".strip()
    return gmail.send_email(to=to, subject=reply_subject, body=body, reply_to_message_id=thread_id)


BOUNCE_SENDERS = (
    "mailer-daemon",
    "postmaster",
    "mail delivery subsystem",
    "mail delivery system",
)

BOUNCE_MARKERS = (
    "delivery status notification",
    "message not delivered",
    "delivery has failed",
    "undeliverable",
    "address not found",
    "recipient address rejected",
    "permanent failure",
    "user unknown",
)


def _looks_like_bounce(message: dict) -> bool:
    sender = (message.get("from_raw") or message.get("from_email") or "").lower()
    subject = (message.get("subject") or "").lower()
    body = (message.get("body") or message.get("snippet") or "").lower()
    return any(s in sender for s in BOUNCE_SENDERS) and (
        any(m in subject for m in BOUNCE_MARKERS)
        or any(m in body for m in BOUNCE_MARKERS)
    )


def _extract_bounced_email(message: dict) -> str | None:
    body = message.get("body") or ""
    patterns = [
        r"Final-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)",
        r"Original-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)",
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(".,;:<>").lower()
    return None


def run() -> dict:
    s = get_settings()
    with run_context("reply", {"autoreply_enabled": s.enable_reply_autoreply}) as run:
        try:
            from app.integrations import gmail
            messages = gmail.list_recent_replies()
        except Exception as e:
            run.warn("gmail_list_failed", error=str(e))
            run.output = {"processed": 0, "skipped_due_to_gmail": True}
            return run.output

        processed = 0
        auto_replied = 0
        escalated = 0
        unsubscribed = 0
        bounced = 0

        for msg in messages:
            # Skip if we already saw this gmail id
            existing = db.select("replies", gmail_message_id=msg.get("id"))
            if existing:
                continue

            if _looks_like_bounce(msg):
                bounced_email = _extract_bounced_email(msg)
                marked = db.mark_outreach_bounced(
                    bounced_email or "",
                    reason="gmail_delivery_failure",
                )
                _record_reply(msg, "unknown", 1.0, False, None, False)
                run.warn(
                    "bounce_processed",
                    bounced_email=bounced_email,
                    outreach_rows_marked=marked,
                    gmail_message_id=msg.get("id"),
                )
                bounced += 1
                processed += 1
                continue

            if not db.find_prospect_by_email(msg.get("from_email")):
                run.info(
                    "reply_skipped_unknown_sender",
                    from_email=msg.get("from_email"),
                    subject=msg.get("subject"),
                    gmail_message_id=msg.get("id"),
                )
                continue

            cls = _classify(msg)
            intent = cls.get("intent", "unknown")
            confidence = float(cls.get("confidence") or 0.0)

            # Hard side-effect: unsubscribe goes to the unsubscribe list immediately.
            if intent == "unsubscribe":
                db.add_unsubscribe(msg.get("from_email"), reason="replied_unsubscribe")
                _record_reply(msg, intent, confidence, False, None, True)
                # Notify operator via approvals queue (informational; no action needed)
                db.insert(
                    "approvals",
                    {
                        "kind": "reply",
                        "target_id": db.insert(
                            "agent_runs",
                            {"agent": "reply", "status": "completed", "input": {"info": "noop"}},
                        )["id"],
                        "payload": {"from": msg.get("from_email"), "intent": intent, "body": msg.get("body")},
                        "reason_for_review": "unsubscribe_received (already actioned)",
                    },
                )
                unsubscribed += 1
                processed += 1
                continue

            gate = safety.reply_autoreply_gate(
                intent=intent, confidence=confidence, body=msg.get("body") or ""
            )

            if gate.passed and s.enable_reply_autoreply:
                body = _draft_autoreply(msg, intent)
                # Run the auto-reply body through the outbound banned-phrase check
                if body and not safety.find_banned_phrases(body):
                    try:
                        _send_reply(
                            to=msg["from_email"],
                            subject=msg.get("subject") or "",
                            body=body,
                            thread_id=msg.get("thread_id"),
                        )
                        _record_reply(msg, intent, confidence, True, body, False)
                        auto_replied += 1
                        processed += 1
                        continue
                    except Exception as e:
                        run.error("autoreply_send_failed", error=str(e))

            # Default path: escalate to approval queue
            rec = _record_reply(msg, intent, confidence, False, None, True)
            db.insert(
                "approvals",
                {
                    "kind": "reply",
                    "target_id": rec["id"],
                    "payload": {
                        "from": msg.get("from_email"),
                        "subject": msg.get("subject"),
                        "intent": intent,
                        "confidence": confidence,
                        "body": msg.get("body"),
                        "gate_failures": gate.failures,
                    },
                    "reason_for_review": ", ".join(gate.failures) or "escalate_intent",
                },
            )
            escalated += 1
            processed += 1

        run.output = {
            "processed": processed,
            "auto_replied": auto_replied,
            "escalated": escalated,
            "unsubscribed": unsubscribed,
            "bounced": bounced,
        }
        return run.output
