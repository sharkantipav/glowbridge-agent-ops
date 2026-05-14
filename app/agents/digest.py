"""Daily operator digest for lead-generation visibility."""
from __future__ import annotations

from datetime import UTC, datetime

from app import db
from app.agents.base import run_context
from app.config import get_settings


def _today_start_iso() -> str:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _count_since(table: str, time_col: str, since: str, **filters) -> int:
    q = db.db().table(table).select("id", count="exact").gte(time_col, since)
    for key, value in filters.items():
        q = q.eq(key, value)
    res = q.execute()
    return int(res.count or 0)


def _pending_approvals_count() -> int:
    res = (
        db.db()
        .table("approvals")
        .select("id", count="exact")
        .eq("state", "pending")
        .execute()
    )
    return int(res.count or 0)


def _recent_replies(limit: int = 5) -> list[dict]:
    return (
        db.db()
        .table("replies")
        .select("from_email,subject,intent,confidence,created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def _format_digest(metrics: dict, replies: list[dict], admin_url: str) -> str:
    lines = [
        "GlowBridge daily lead report",
        "",
        f"Prospects added today: {metrics['prospects_added']}",
        f"Prospects researched today: {metrics['researched']}",
        f"First-touch/follow-up emails sent today: {metrics['sent']}",
        f"Bounced emails today: {metrics['bounced']}",
        f"Replies received today: {metrics['replies']}",
        f"Interested / wants call today: {metrics['hot_replies']}",
        f"Pending approval items: {metrics['pending_approvals']}",
        "",
        "Recent replies:",
    ]
    if not replies:
        lines.append("- None yet.")
    for reply in replies:
        confidence = reply.get("confidence")
        confidence_text = f"{float(confidence):.2f}" if confidence is not None else "n/a"
        lines.append(
            f"- {reply.get('intent')} ({confidence_text}) from {reply.get('from_email')}: "
            f"{reply.get('subject') or '(no subject)'}"
        )
    lines.extend(
        [
            "",
            f"Admin: {admin_url}",
            "",
            "Recommended next move: handle hot replies first, then pending approvals.",
        ]
    )
    return "\n".join(lines)


def run() -> dict:
    s = get_settings()
    since = _today_start_iso()
    admin_url = f"{s.app_base_url.rstrip('/')}/admin"

    with run_context("digest", {"since": since}) as run:
        metrics = {
            "prospects_added": _count_since("prospects", "created_at", since),
            "researched": _count_since("research", "created_at", since),
            "sent": _count_since("outreach", "sent_at", since, status="sent"),
            "bounced": _count_since("outreach", "bounced_at", since, status="bounced"),
            "replies": _count_since("replies", "created_at", since),
            "hot_replies": _count_since("replies", "created_at", since, intent="interested")
            + _count_since("replies", "created_at", since, intent="wants_call"),
            "pending_approvals": _pending_approvals_count(),
        }
        replies = _recent_replies()
        body = _format_digest(metrics, replies, admin_url)

        try:
            from app.integrations import gmail

            message_id = gmail.send_email(
                to=s.operator_email,
                subject="GlowBridge daily lead report",
                body=body,
            )
            run.info("digest_sent", message_id=message_id, metrics=metrics)
            run.output = {"sent": True, "message_id": message_id, "metrics": metrics}
        except Exception as e:
            run.error("digest_send_failed", error=str(e), metrics=metrics)
            run.output = {"sent": False, "error": str(e), "metrics": metrics}
        return run.output
