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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class SendBudget:
    enabled: bool
    remaining: int
    reason: str | None = None


def _send_budget(*, max_daily: int, sent_today: int) -> SendBudget:
    if max_daily <= 0:
        return SendBudget(enabled=False, remaining=0, reason="daily_outreach_cap_disabled")
    remaining = max(max_daily - sent_today, 0)
    if remaining <= 0:
        return SendBudget(
            enabled=False,
            remaining=0,
            reason=f"daily_outreach_cap_reached ({sent_today}/{max_daily})",
        )
    return SendBudget(enabled=True, remaining=remaining)


def _is_hard_block(failures: list[str]) -> bool:
    return any(
        f.startswith(
            (
                "unsubscribed",
                "banned_phrase",
                "fabrication",
                "placeholder_email",
                "no_reply_email",
            )
        )
        for f in failures
    )


def _approval_state_for_outreach_status(status: str) -> str | None:
    if status == "sent":
        return "approved"
    if status in {"blocked", "bounced", "rejected"}:
        return "rejected"
    return None


def _sync_outreach_approval(outreach_id: str, status: str) -> None:
    state = _approval_state_for_outreach_status(status)
    if not state:
        return
    db.db().table("approvals").update(
        {"state": state, "decided_by": "system", "decided_at": "now()"}
    ).eq("kind", "outreach").eq("target_id", outreach_id).eq("state", "pending").execute()


def _send_queued_under_budget(budget: SendBudget, already_sent_this_run: int, run) -> int:
    if not budget.enabled or already_sent_this_run >= budget.remaining:
        return 0

    sent = 0
    remaining = budget.remaining - already_sent_this_run
    for row in db.queued_outreach_to_send(limit=remaining):
        prospect = row.get("prospects") or {}
        gate = safety.outreach_send_gate(
            body=row.get("body") or "",
            subject=row.get("subject") or "",
            to_email=prospect.get("email"),
            score=prospect.get("score"),
            is_pest_control=True,
        )
        if not gate.passed:
            status = "blocked" if _is_hard_block(gate.failures) else "queued"
            patch = {"gate_failures": gate.failures}
            if status == "blocked":
                patch["status"] = "blocked"
            db.db().table("outreach").update(patch).eq("id", row["id"]).execute()
            _sync_outreach_approval(row["id"], status)
            run.warn(
                "queued_outreach_blocked",
                outreach_id=row["id"],
                prospect_id=row.get("prospect_id"),
                failures=gate.failures,
            )
            continue

        try:
            msg_id = _send_via_gmail(
                to=prospect["email"],
                subject=row["subject"],
                body=row["body"],
            )
            db.db().table("outreach").update(
                {"status": "sent", "gmail_message_id": msg_id, "sent_at": "now()"}
            ).eq("id", row["id"]).execute()
            _sync_outreach_approval(row["id"], "sent")
            sent += 1
            run.info(
                "queued_outreach_sent",
                outreach_id=row["id"],
                prospect_id=row.get("prospect_id"),
                gmail_id=msg_id,
            )
        except Exception as e:
            db.db().table("outreach").update(
                {"gate_failures": [f"send_failed: {e}"]}
            ).eq("id", row["id"]).execute()
            run.error("queued_outreach_send_failed", outreach_id=row["id"], error=str(e))
    return sent


def run(limit: int = 25) -> dict:
    s = get_settings()
    sent_today = db.count_outreach_sent_today() if s.enable_outreach_send else 0
    budget = _send_budget(max_daily=s.max_outreach_sends_per_day, sent_today=sent_today)
    with run_context(
        "outreach",
        {
            "limit": limit,
            "send_enabled": s.enable_outreach_send,
            "sent_today": sent_today,
            "send_budget_remaining": budget.remaining,
        },
    ) as run:
        targets = db.outreach_ready_prospects(limit=limit)
        run.info("outreach_targets", count=len(targets))

        sent = 0
        queued = 0
        blocked = 0
        skipped = 0

        if s.enable_outreach_send:
            sent += _send_queued_under_budget(budget, sent, run)

        for p in targets:
            if s.enable_outreach_send and sent >= budget.remaining:
                break
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
                hard_block = _is_hard_block(gate.failures)
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
            if not s.enable_outreach_send or not budget.enabled or sent >= budget.remaining:
                # Dry-run: queue for human eyes anyway, with no failure reason.
                row["status"] = "queued"
                inserted = db.insert("outreach", row)
                review_reason = "ENABLE_OUTREACH_SEND=false (dry run)"
                if s.enable_outreach_send and (not budget.enabled or sent >= budget.remaining):
                    review_reason = budget.reason or "daily_outreach_cap_reached"
                db.insert(
                    "approvals",
                    {
                        "kind": "outreach",
                        "target_id": inserted["id"],
                        "payload": {"subject": subject, "body": body, "to": p.get("email")},
                        "reason_for_review": review_reason,
                    },
                )
                queued += 1
                run.info("outreach_send_queued", prospect_id=p["id"], reason=review_reason)
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
