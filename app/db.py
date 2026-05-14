"""Supabase client + thin typed helpers.

The backend uses the service-role key, so it bypasses RLS. Never import
this module from anywhere that could be reached by an unauthenticated
HTTP request without an admin check.
"""
from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def db() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


# ---------- Generic helpers ----------

def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    res = db().table(table).insert(row).execute()
    return res.data[0] if res.data else {}


def update(table: str, row_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    res = db().table(table).update(patch).eq("id", row_id).execute()
    return res.data[0] if res.data else {}


def select(table: str, **filters: Any) -> list[dict[str, Any]]:
    q = db().table(table).select("*")
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data or []


# ---------- Domain-specific helpers ----------

def is_unsubscribed(email: str) -> bool:
    if not email:
        return False
    res = db().table("unsubscribes").select("id").ilike("email", email).limit(1).execute()
    return bool(res.data)


def add_unsubscribe(email: str, reason: str = "manual") -> None:
    if not email:
        return
    db().table("unsubscribes").upsert({"email": email.lower(), "reason": reason}).execute()


def find_prospect_by_website(website: str) -> dict[str, Any] | None:
    if not website:
        return None
    res = (
        db()
        .table("prospects")
        .select("*")
        .ilike("website", website)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def pending_research_prospects(limit: int = 50) -> list[dict[str, Any]]:
    """Prospects with a website but no research record yet."""
    candidate_limit = max(limit * 5, limit)
    res = (
        db()
        .table("prospects")
        .select("*")
        .not_.is_("website", "null")
        .order("created_at", desc=True)
        .limit(candidate_limit)
        .execute()
    )
    candidates = res.data or []
    if not candidates:
        return []

    prospect_ids = [p["id"] for p in candidates if p.get("id")]
    research_res = (
        db()
        .table("research")
        .select("prospect_id")
        .in_("prospect_id", prospect_ids)
        .execute()
    )
    researched_ids = {r["prospect_id"] for r in research_res.data or [] if r.get("prospect_id")}
    return _unresearched_prospects(candidates, researched_ids, limit)


def _unresearched_prospects(
    candidates: list[dict[str, Any]], researched_ids: set[str], limit: int
) -> list[dict[str, Any]]:
    return [p for p in candidates if p.get("id") not in researched_ids][:limit]


def outreach_ready_prospects(limit: int = 50) -> list[dict[str, Any]]:
    """Prospects with research done, score >= 8, email present, no outreach yet."""
    res = (
        db()
        .table("prospects")
        .select("*, research(*), outreach(id, status)")
        .gte("score", 8)
        .not_.is_("email", "null")
        .limit(limit)
        .execute()
    )
    out = []
    for p in res.data or []:
        if not p.get("research"):
            continue
        if _has_existing_outreach(p.get("outreach") or []):
            continue
        out.append(p)
    return out


def _has_existing_outreach(outreach_rows: list[dict[str, Any]]) -> bool:
    return bool(outreach_rows)


def queued_outreach_to_send(limit: int = 25) -> list[dict[str, Any]]:
    """Clean queued outreach rows that can be retried under today's send budget.

    The outreach agent uses `queued` for two very different cases:
    - safe emails paused because the daily cap was reached (gate_failures is null)
    - emails requiring human review (gate_failures is not null)

    Only the first category should auto-send on a later day.
    """
    res = (
        db()
        .table("outreach")
        .select("*, prospects(email, score, company_name)")
        .eq("status", "queued")
        .is_("gate_failures", "null")
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return res.data or []


def count_outreach_sent_today() -> int:
    """Count outbound outreach sends since midnight UTC.

    This is a coarse cap. For a cold-outreach safety brake, UTC is good enough:
    it prevents a deploy/retry loop from sending unbounded emails in one day.
    """
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    res = (
        db()
        .table("outreach")
        .select("id", count="exact")
        .eq("status", "sent")
        .gte("sent_at", since)
        .execute()
    )
    return int(res.count or 0)


def log(
    agent: str,
    level: str,
    message: str,
    data: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> None:
    try:
        db().table("agent_logs").insert(
            {
                "run_id": run_id,
                "agent": agent,
                "level": level,
                "message": message,
                "data": data,
            }
        ).execute()
    except Exception:
        # Never let logging crash an agent run.
        pass
