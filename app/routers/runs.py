"""Manual run endpoints — POST /runs/{agent} to trigger any agent on demand.

Useful for testing without waiting for cron.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app import db, llm
from app.agents import outreach, prospect, reply, research, social
from app.config import get_settings
from app.routers.auth_dep import require_admin

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_admin)])


@router.post("/prospect")
def run_prospect(target: int = 25):
    return prospect.run(target=target)


@router.post("/research")
def run_research(limit: int = 50):
    return research.run(limit=limit)


@router.post("/outreach")
def run_outreach(limit: int = 25):
    return outreach.run(limit=limit)


@router.post("/reply")
def run_reply():
    return reply.run()


@router.post("/social")
def run_social():
    return social.run()


@router.post("/create-test-assistant")
def create_test_assistant(
    company_name: str = Body("GlowBridge Test Pest Co.", embed=True),
    area_code: str | None = Body(None, embed=True),
):
    """Provision a real Vapi assistant + phone number for end-to-end voice testing.

    Use this to be Customer #0: call the returned phone_number from your cell,
    listen to the AI, iterate the prompt until it sounds right.

    Body:
      { "company_name": "Acme Pest", "area_code": "732" }   (both optional)
    """
    from app.integrations import vapi as vapi_int

    s = get_settings()

    # Generate a stock call flow on the fly using the same LLM the Customer
    # agent uses — keeps the tested prompt identical to what real customers get.
    flow_system = """\
You are designing a draft call-handling flow for an AI receptionist for a small
pest control company. Return a JSON object with these keys:
  greeting, questions[], boundaries[], handoff_method, handoff_template, after_hours_note
The boundaries MUST include: never quote prices, never guarantee outcomes,
never diagnose pests, distress callback within 30 minutes during business hours.
Reply ONLY with JSON.
"""
    try:
        call_flow = llm.json_call(
            system=flow_system,
            user=f"Company: {company_name}",
            tier="smart",
            max_tokens=900,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"call_flow generation failed: {e}") from e

    server_url = f"{s.app_base_url.rstrip('/')}/webhooks/vapi"
    try:
        assistant = vapi_int.create_assistant(
            company_name=company_name,
            call_flow=call_flow,
            server_url=server_url,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"vapi assistant creation failed: {e}") from e

    try:
        phone = vapi_int.create_phone_number(assistant_id=assistant["id"], area_code=area_code)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"assistant created ({assistant['id']}) but phone provisioning failed: {e}",
        ) from e

    # Persist as a synthetic customer so it shows up in the dashboard
    customer = db.insert(
        "customers",
        {
            "company_name": f"[TEST] {company_name}",
            "contact_email": s.operator_email,
            "status": "test_call_approved",
            "vapi_assistant_id": assistant["id"],
            "vapi_phone_number": phone.get("number"),
            "vapi_provisioned_at": "now()",
            "test_call_approved_at": "now()",
            "call_flow_draft": call_flow,
        },
    )

    return {
        "ok": True,
        "customer_id": customer["id"],
        "assistant_id": assistant["id"],
        "phone_number": phone.get("number"),
        "instructions": (
            f"Call {phone.get('number')} from your cell — you should hear the AI greet "
            f"you as the {company_name} after-hours assistant. To iterate the system "
            f"prompt: PATCH /assistant/{assistant['id']} via the Vapi dashboard or call "
            "vapi.update_assistant() in code."
        ),
    }


@router.post("/{agent}")
def run_unknown(agent: str):
    raise HTTPException(status_code=404, detail=f"unknown agent: {agent}")
