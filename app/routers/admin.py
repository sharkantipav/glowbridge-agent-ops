"""Admin dashboard — minimal Jinja page at /admin showing today's activity."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import db
from app.routers.auth_dep import require_admin

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def _since_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, _: None = Depends(require_admin)):
    since = _since_iso(24)

    # Stats
    runs = (
        db.db()
        .table("agent_runs")
        .select("agent,status")
        .gte("started_at", since)
        .execute()
        .data
        or []
    )
    runs_by_agent: dict[str, dict[str, int]] = {}
    for r in runs:
        bucket = runs_by_agent.setdefault(r["agent"], {"completed": 0, "failed": 0, "started": 0})
        bucket[r["status"]] = bucket.get(r["status"], 0) + 1

    pending_approvals = (
        db.db().table("approvals").select("id,kind,reason_for_review,created_at,payload")
        .eq("state", "pending").order("created_at", desc=True).limit(50).execute().data or []
    )

    recent_outreach = (
        db.db().table("outreach").select("id,subject,status,gate_failures,created_at,sent_at,prospect_id")
        .order("created_at", desc=True).limit(20).execute().data or []
    )

    recent_replies = (
        db.db().table("replies").select("id,from_email,subject,intent,confidence,auto_replied,escalated,created_at")
        .order("created_at", desc=True).limit(20).execute().data or []
    )

    customer_count = (
        db.db().table("customers").select("id", count="exact").execute().count or 0
    )
    prospect_count = (
        db.db().table("prospects").select("id", count="exact").execute().count or 0
    )
    unsub_count = (
        db.db().table("unsubscribes").select("id", count="exact").execute().count or 0
    )

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "runs_by_agent": runs_by_agent,
            "pending_approvals": pending_approvals,
            "recent_outreach": recent_outreach,
            "recent_replies": recent_replies,
            "customer_count": customer_count,
            "prospect_count": prospect_count,
            "unsub_count": unsub_count,
        },
    )


@router.get("/admin/health")
def health(_: None = Depends(require_admin)):
    return {"ok": True}
