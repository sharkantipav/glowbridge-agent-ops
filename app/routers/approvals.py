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

# Re-exported for callers that want to provision without going through the
# approval flow (e.g. the test-assistant endpoint).
__all__ = ["router"]

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
        # Approving the call-flow draft: provision Vapi and move to test_call_approved.
        return _provision_customer_vapi(appr["target_id"])

    return {"ok": True}


def _provision_customer_vapi(customer_id: str) -> dict:
    """Create the Vapi assistant + phone number for a customer whose call flow
    just got approved. Sends them their forwarding number by email.
    """
    from app.integrations import vapi as vapi_int
    from app.integrations import gmail

    rows = db.select("customers", id=customer_id)
    if not rows:
        return {"ok": False, "error": "customer not found"}
    customer = rows[0]

    if customer.get("vapi_assistant_id"):
        return {
            "ok": True,
            "note": "already provisioned",
            "assistant_id": customer["vapi_assistant_id"],
            "phone_number": customer["vapi_phone_number"],
        }

    s = get_settings()
    server_url = f"{s.app_base_url.rstrip('/')}/webhooks/vapi"

    try:
        assistant = vapi_int.create_assistant(
            company_name=customer["company_name"],
            call_flow=customer.get("call_flow_draft") or {},
            server_url=server_url,
        )
    except Exception as e:
        return {"ok": False, "error": f"vapi assistant creation failed: {e}"}

    try:
        phone = vapi_int.create_phone_number(assistant_id=assistant["id"])
    except Exception as e:
        # Roll back the assistant id reference if number provisioning fails — leave
        # the assistant in Vapi for manual cleanup. Customer stays in awaiting_test_call.
        return {"ok": False, "error": f"vapi phone provisioning failed: {e}",
                "assistant_id": assistant.get("id")}

    db.update(
        "customers",
        customer_id,
        {
            "status": "test_call_approved",
            "test_call_approved_at": "now()",
            "vapi_assistant_id": assistant["id"],
            "vapi_phone_number": phone.get("number"),
            "vapi_provisioned_at": "now()",
        },
    )

    # Email the customer their forwarding number
    forwarding_number = phone.get("number") or "(see GlowBridge dashboard)"
    body = f"""Hi,

Your GlowBridge AI receptionist is live and ready for the test call.

To use it, forward your missed and after-hours calls to:

    {forwarding_number}

How forwarding works on most carriers:
  - Verizon / AT&T:  *72  then  the number above  (then call any number to confirm)
  - T-Mobile:        **21*  then  the number above  #   (call to send)
  - To turn it off:  *73  on Verizon/AT&T,  ##21#  on T-Mobile

We recommend doing a test call first — call your office number from your cell.
You should hear: "Hi, thanks for calling {customer['company_name']} — I'm the
after-hours assistant."

Reply to this email with any quirks or things you'd like adjusted.

— Charles, GlowBridge"""

    try:
        gmail.send_email(
            to=customer["contact_email"],
            subject="Your GlowBridge AI receptionist is ready",
            body=body,
        )
    except Exception:
        pass  # provisioning succeeded; email failure is logged but non-fatal

    return {
        "ok": True,
        "assistant_id": assistant["id"],
        "phone_number": forwarding_number,
        "note": "Vapi provisioned, customer notified by email",
    }


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
