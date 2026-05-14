"""Follow-up agent for cold outreach that got no reply.

Sends one short, safe follow-up after the initial email has had time to breathe.
This is deliberately conservative: no pressure, no fake claims, no guarantee
language, and never follows up if the prospect replied, bounced, or unsubscribed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app import db, safety
from app.agents.base import run_context
from app.agents.outreach import _send_budget, _send_via_gmail
from app.config import get_settings

FOLLOWUP_DELAY_DAYS = 2


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_followup_subject(subject: str | None) -> bool:
    return (subject or "").lower().startswith("re:")


def _followup_body(company_name: str, original_subject: str) -> str:
    return (
        f"Quick follow-up on my note about after-hours calls at {company_name}.\n\n"
        "GlowBridge can answer missed calls, collect the caller's name, phone, address, "
        "and pest issue, then send the details to your team. Your team still handles pricing conversations.\n\n"
        "Would it be useful if I set up a short test call for your company?"
    )


def _has_reply_from(email: str | None) -> bool:
    if not email:
        return False
    rows = db.db().table("replies").select("id").ilike("from_email", email).limit(1).execute().data
    return bool(rows)


def _already_followed_up(prospect_id: str) -> bool:
    rows = (
        db.db()
        .table("outreach")
        .select("id,subject")
        .eq("prospect_id", prospect_id)
        .execute()
        .data
        or []
    )
    return any(_is_followup_subject(r.get("subject")) for r in rows)


def _eligible_sent_rows(limit: int, delay_days: int = FOLLOWUP_DELAY_DAYS) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(days=delay_days)
    rows = (
        db.db()
        .table("outreach")
        .select("*, prospects(company_name,email,score)")
        .eq("status", "sent")
        .order("sent_at")
        .limit(limit * 5)
        .execute()
        .data
        or []
    )

    out: list[dict] = []
    for row in rows:
        if len(out) >= limit:
            break
        sent_at = _parse_dt(row.get("sent_at"))
        if not sent_at or sent_at > cutoff:
            continue
        if _is_followup_subject(row.get("subject")):
            continue
        prospect = row.get("prospects") or {}
        email = prospect.get("email")
        if safety.email_risk_reason(email) or db.is_unsubscribed(email):
            continue
        if _has_reply_from(email):
            continue
        if _already_followed_up(row["prospect_id"]):
            continue
        out.append(row)
    return out


def run(limit: int = 15) -> dict:
    s = get_settings()
    sent_today = db.count_outreach_sent_today() if s.enable_outreach_send else 0
    daily_cap = s.max_outreach_sends_per_day + max(s.max_followup_sends_per_day, 0)
    budget = _send_budget(max_daily=daily_cap, sent_today=sent_today)

    with run_context(
        "followup",
        {
            "limit": limit,
            "send_enabled": s.enable_outreach_send,
            "sent_today": sent_today,
            "daily_cap": daily_cap,
            "budget_remaining": budget.remaining,
        },
    ) as run:
        targets = _eligible_sent_rows(limit=limit)
        run.info("followup_targets", count=len(targets))

        sent = 0
        skipped = 0
        queued = 0
        blocked = 0

        for row in targets:
            if not s.enable_outreach_send or not budget.enabled or sent >= budget.remaining:
                queued += 1
                continue

            prospect = row.get("prospects") or {}
            subject = f"Re: {row.get('subject') or 'after-hours calls'}"
            body = _followup_body(prospect.get("company_name") or "your company", row.get("subject") or "")
            gate = safety.outreach_send_gate(
                body=body,
                subject=subject,
                to_email=prospect.get("email"),
                score=prospect.get("score"),
                is_pest_control=True,
            )
            if not gate.passed:
                blocked += 1
                run.warn("followup_blocked", prospect_id=row["prospect_id"], failures=gate.failures)
                continue

            try:
                msg_id = _send_via_gmail(to=prospect["email"], subject=subject, body=body)
                db.insert(
                    "outreach",
                    {
                        "prospect_id": row["prospect_id"],
                        "research_id": row.get("research_id"),
                        "subject": subject,
                        "body": body,
                        "status": "sent",
                        "gmail_message_id": msg_id,
                        "sent_at": "now()",
                    },
                )
                sent += 1
                run.info("followup_sent", prospect_id=row["prospect_id"], gmail_id=msg_id)
            except Exception as e:
                skipped += 1
                run.error("followup_send_failed", prospect_id=row["prospect_id"], error=str(e))

        run.output = {"sent": sent, "queued": queued, "blocked": blocked, "skipped": skipped}
        return run.output
