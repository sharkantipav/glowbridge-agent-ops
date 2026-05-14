from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import db
from app.config import get_settings

router = APIRouter(prefix="/public", tags=["public"])


class SiteLeadIn(BaseModel):
    source: Literal["demo_call", "pilot_setup", "audit"] = "pilot_setup"
    name: str = Field(min_length=1, max_length=120)
    business_name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=7, max_length=40)
    email: str = Field(min_length=3, max_length=240)
    industry: str = Field(default="Pest Control", max_length=80)
    website: str | None = Field(default=None, max_length=240)
    avg_job_value: str | None = Field(default=None, max_length=80)
    missed_calls_per_week: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("email")
    @classmethod
    def email_must_look_valid(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or "." not in cleaned.rsplit("@", 1)[-1]:
            raise ValueError("invalid email")
        return cleaned


def _lead_payload(lead: SiteLeadIn) -> dict:
    return {
        "source": lead.source,
        "name": lead.name.strip(),
        "business_name": lead.business_name.strip(),
        "phone": lead.phone.strip(),
        "email": str(lead.email).strip().lower(),
        "industry": lead.industry.strip(),
        "website": (lead.website or "").strip() or None,
        "avg_job_value": (lead.avg_job_value or "").strip() or None,
        "missed_calls_per_week": (lead.missed_calls_per_week or "").strip() or None,
        "notes": (lead.notes or "").strip() or None,
    }


def _notification_body(payload: dict) -> str:
    return "\n".join(
        [
            "New GlowBridge website lead",
            "",
            f"Source: {payload['source']}",
            f"Name: {payload['name']}",
            f"Business: {payload['business_name']}",
            f"Phone: {payload['phone']}",
            f"Email: {payload['email']}",
            f"Industry: {payload['industry']}",
            f"Website: {payload.get('website') or '-'}",
            f"Average job value: {payload.get('avg_job_value') or '-'}",
            f"Missed calls/week: {payload.get('missed_calls_per_week') or '-'}",
            "",
            f"Notes: {payload.get('notes') or '-'}",
        ]
    )


def _notify_operator(payload: dict) -> str | None:
    s = get_settings()
    try:
        from app.integrations import gmail

        return gmail.send_email(
            to=s.operator_email,
            subject=f"New GlowBridge lead: {payload['business_name']}",
            body=_notification_body(payload),
        )
    except Exception:
        return None


@router.post("/site-leads")
def create_site_lead(lead: SiteLeadIn):
    payload = _lead_payload(lead)
    if payload["industry"].lower() != "pest control":
        # Keep it open for adjacent home services, but flag Charles to review fit.
        reason = f"website_lead_non_core_industry ({payload['industry']})"
    else:
        reason = "website_lead"

    try:
        run = db.insert(
            "agent_runs",
            {
                "agent": "site_lead",
                "status": "completed",
                "input": payload,
                "output": {},
            },
        )
        gmail_id = _notify_operator(payload)
        db.insert(
            "approvals",
            {
                "kind": "customer_action",
                "target_id": run["id"],
                "payload": {**payload, "operator_notification_gmail_id": gmail_id},
                "reason_for_review": reason,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="lead_capture_failed") from e

    return {"ok": True}
