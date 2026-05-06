"""Approval queue endpoints — list / approve / reject items in `approvals`.

Approving an outreach item flips its status to 'approved' and (if auto-send is
enabled) sends it. Rejecting flips status to 'rejected'.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException

from app import db
from app.config import get_settings
from app.routers.auth_dep import require_admin

router = APIRouter(prefix="/admin/approvals", tags=["approvals"], dependencies=[Depends(require_admin)])


@router.get("")
def list_approvals(
    state: Literal["pending", "approved", "rejected", "expired"] = "pending",
    kind: str | None = None,
    limit: int = 50,
):
    q = db.db().table("approvals").select("*").eq("state", state).order("created_at", desc=True).limit(limit)
    if kind:
        q = q.eq("kind", kind)
    return q.execute().data or []


@router.post("/{approval_id}/approve")
def approve(approval_id: str, decided_by: str = Body("charles", embed=True)):
    rows = db.select("approvals", id=approval_id)
    if not rows:
        raise HTTPException(status_code=404, detail="approval not found")
    appr = rows[0]
    if appr["state"] != "pending":
        raise HTTPException(status_code=409, detail=f"already {appr['state']}")

    db.update("approvals", approval_id, {"state": "approved", "decided_by": decided_by, "decided_at": "now()"})

    s = get_settings()
    if appr["kind"] == "outreach":
        # Flip outreach row + optionally send
        outreach_id = appr["target_id"]
        db.update("outreach", outreach_id, {"status": "approved"})
        if s.enable_outreach_send:
            from app.integrations import gmail
            payload = appr["payload"]
            try:
                gmail_id = gmail.send_email(
                    to=payload["to"], subject=payload["subject"], body=payload["body"]
                )
                db.update("outreach", outreach_id, {"status": "sent", "gmail_message_id": gmail_id, "sent_at": "now()"})
                return {"ok": True, "sent": True, "gmail_message_id": gmail_id}
            except Exception as e:
                return {"ok": True, "sent": False, "error": str(e)}
        return {"ok": True, "sent": False, "note": "outreach send disabled"}

    if appr["kind"] == "reply":
        # Approving a queued reply means: send the suggested auto-reply (if present in payload).
        payload = appr["payload"] or {}
        if not payload.get("draft_reply"):
            return {"ok": True, "note": "no draft_reply in payload — nothing to send"}
        if not s.enable_reply_autoreply:
            return {"ok": True, "sent": False, "note": "reply autoreply disabled"}
        from app.integrations import gmail
        try:
            gmail_id = gmail.send_email(
                to=payload["from"], subject=payload.get("subject") or "", body=payload["draft_reply"]
            )
            return {"ok": True, "sent": True, "gmail_message_id": gmail_id}
        except Exception as e:
            return {"ok": True, "sent": False, "error": str(e)}

    if appr["kind"] == "social":
        db.update("social_posts", appr["target_id"], {"status": "queued"})
        return {"ok": True, "note": "social post moved to queued (manual post)"}

    if appr["kind"] == "customer_action":
        # Approving the call-flow draft: customer moves to test_call_approved
        db.update(
            "customers",
            appr["target_id"],
            {"status": "test_call_approved", "test_call_approved_at": "now()"},
        )
        return {"ok": True, "note": "customer approved for test call"}

    return {"ok": True}


@router.post("/{approval_id}/reject")
def reject(approval_id: str, reason: str = Body("", embed=True), decided_by: str = Body("charles", embed=True)):
    rows = db.select("approvals", id=approval_id)
    if not rows:
        raise HTTPException(status_code=404, detail="approval not found")
    appr = rows[0]
    if appr["state"] != "pending":
        raise HTTPException(status_code=409, detail=f"already {appr['state']}")

    db.update(
        "approvals",
        approval_id,
        {
            "state": "rejected",
            "decided_by": decided_by,
            "decided_at": "now()",
        },
    )

    if appr["kind"] == "outreach":
        db.update("outreach", appr["target_id"], {"status": "rejected", "rejected_reason": reason})
    elif appr["kind"] == "social":
        db.update("social_posts", appr["target_id"], {"status": "rejected"})
    return {"ok": True, "reason": reason}
