"""Outreach agent — draft personalized emails, gate, send or queue.

Pulls prospects with score>=8, email present, no existing outreach. For each:
  1. Drafts a <90-word, plain-text email that mentions the pain signal.
  2. Runs the hard safety gate (banned phrases, word count, unsubscribe, etc.).
  3. If the gate passes AND ENABLE_OUTREACH_SEND is true, sends via Gmail.
  4. Otherwise writes a row in `approvals` for Charles to review.

The model is told the rules. The gate enforces them anyway.
"""
from __future__ import annotations

import json

from app import db, llm, safety
from app.agents.base import run_context
from app.config import get_settings

OUTREACH_SYSTEM = """\
You write very short cold emails to pest control company owners on behalf of GlowBridge,
an AI receptionist service that answers missed and after-hours calls.

CONSTRAINTS — non-negotiable:
- Total email body must be UNDER 90 words.
- Plain text, no HTML, no fancy formatting, no greetings beyond a first name.
- Reference one concrete observation from the research (the pain_signal).
- Subject line under 60 characters, no clickbait, no all-caps.
- Offer: $199 setup + $99/month, billed only AFTER they approve a test call.
  If they're not comfortable going live, the setup fee is refunded.
- One soft CTA: ask if they'd like to see a 5-minute demo.

NEVER:
- Claim guaranteed bookings or revenue.
- Say "AI quotes prices" or "AI guarantees" anything.
- Promise a number of jobs/leads/customers.
- Use phrases like "double your bookings" or "never miss a call".
- Fabricate customer references or case studies.
- Use the word "guaranteed".

Reply ONLY with JSON:
{ "subject": string, "body": string }
"""


def _draft_one(prospect: dict, research: dict) -> dict | None:
    contact_name = prospect.get("contact_name") or ""
    first_name = contact_name.split()[0] if contact_name else ""
    user = (
        f"Company: {prospect.get('company_name')}\n"
        f"City/State: {prospect.get('city')}, {prospect.get('state')}\n"
        f"Owner first name (if known): {first_name}\n"
        f"Pain signal from research: {research.get('pain_signal')}\n"
        f"Their site advertises emergency: {research.get('advertises_emergency')}\n"
        f"They have an online booking form: {research.get('has_booking_form')}\n"
        f"Voicemail-heavy copy: {research.get('voicemail_heavy')}\n"
        f"\nWrite the email now."
    )
    try:
        return llm.json_call(
            system=OUTREACH_SYSTEM,
            user=user,
            tier="smart",
            temperature=0.5,
            max_tokens=500,
        )
    except Exception:
        return None


def _send_via_gmail(to: str, subject: str, body: str) -> str:
    """Lazy import so the module loads even without Gmail creds set up yet."""
    from app.integrations import gmail

    return gmail.send_email(to=to, subject=subject, body=body)


def run(limit: int = 25) -> dict:
    s = get_settings()
    with run_context("outreach", {"limit": limit, "send_enabled": s.enable_outreach_send}) as run:
        targets = db.outreach_ready_prospects(limit=limit)
        run.info("outreach_targets", count=len(targets))

        sent = 0
        queued = 0
        blocked = 0
        skipped = 0

        for p in targets:
            research_rows = p.get("research") or []
            if not research_rows:
                skipped += 1
                continue
            research = research_rows[0]

            draft = _draft_one(p, research)
            if not draft or not draft.get("subject") or not draft.get("body"):
                skipped += 1
                continue
            subject = (draft["subject"] or "").strip()
            body = (draft["body"] or "").strip()

            gate = safety.outreach_send_gate(
                body=body,
                subject=subject,
                to_email=p.get("email"),
                score=p.get("score"),
                is_pest_control=True,  # Prospect agent already filtered
            )

            row = {
                "prospect_id": p["id"],
                "research_id": research["id"],
                "subject": subject,
                "body": body,
                "status": "draft",
                "gate_failures": gate.failures or None,
            }

            # Decide outcome
            if not gate.passed:
                # Hard-block class: unsubscribed, banned phrase, fabrication
                hard_block = any(
                    f.startswith(("unsubscribed", "banned_phrase", "fabrication"))
                    for f in gate.failures
                )
                row["status"] = "blocked" if hard_block else "queued"
                inserted = db.insert("outreach", row)
                if hard_block:
                    blocked += 1
                    run.warn("outreach_blocked", prospect_id=p["id"], failures=gate.failures)
                else:
                    queued += 1
                    db.insert(
                        "approvals",
                        {
                            "kind": "outreach",
                            "target_id": inserted["id"],
                            "payload": {"subject": subject, "body": body, "to": p.get("email")},
                            "reason_for_review": ", ".join(gate.failures),
                        },
                    )
                    run.info("outreach_queued", prospect_id=p["id"], failures=gate.failures)
                continue

            # Gate passed
            if not s.enable_outreach_send:
                # Dry-run: queue for human eyes anyway, with no failure reason.
                row["status"] = "queued"
                inserted = db.insert("outreach", row)
                db.insert(
                    "approvals",
                    {
                        "kind": "outreach",
                        "target_id": inserted["id"],
                        "payload": {"subject": subject, "body": body, "to": p.get("email")},
                        "reason_for_review": "ENABLE_OUTREACH_SEND=false (dry run)",
                    },
                )
                queued += 1
                run.info("outreach_dry_run_queued", prospect_id=p["id"])
                continue

            try:
                msg_id = _send_via_gmail(to=p["email"], subject=subject, body=body)
                row.update({"status": "sent", "gmail_message_id": msg_id, "sent_at": "now()"})
                db.insert("outreach", row)
                sent += 1
                run.info("outreach_sent", prospect_id=p["id"], gmail_id=msg_id)
            except Exception as e:
                row["status"] = "queued"
                row["gate_failures"] = json.dumps([f"send_failed: {e}"])
                inserted = db.insert("outreach", row)
                db.insert(
                    "approvals",
                    {
                        "kind": "outreach",
                        "target_id": inserted["id"],
                        "payload": {"subject": subject, "body": body, "to": p.get("email")},
                        "reason_for_review": f"send_failed: {e}",
                    },
                )
                queued += 1
                run.error("outreach_send_failed", prospect_id=p["id"], error=str(e))

        run.output = {"sent": sent, "queued": queued, "blocked": blocked, "skipped": skipped}
        return run.output
