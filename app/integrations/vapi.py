"""Vapi voice AI integration — the product layer.

Vapi (vapi.ai) bundles telephony + STT + LLM + TTS behind one API. We use it
so we don't have to wire Twilio/Deepgram/ElevenLabs ourselves.

For each pest-control customer we:
  1. Build a system prompt from their approved call_flow_draft.
  2. Create a Vapi `assistant` (the AI persona).
  3. Provision a `phone-number` and bind it to the assistant.
  4. Email the customer their forwarding number.
  5. When a call ends, Vapi POSTs to /webhooks/vapi with the transcript +
     structured data → we email/SMS the lead to the customer's owner.

Cost rule of thumb at 5 missed calls/day × 2 min ≈ ~$15–30/mo per customer.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

VAPI_BASE = "https://api.vapi.ai"
DEFAULT_END_MESSAGE = "Thanks — someone from the team will reach out shortly. Have a great day."


def _client() -> httpx.Client:
    s = get_settings()
    if not s.vapi_api_key:
        raise RuntimeError("VAPI_API_KEY not set")
    return httpx.Client(
        base_url=VAPI_BASE,
        headers={"Authorization": f"Bearer {s.vapi_api_key}", "Content-Type": "application/json"},
        timeout=30,
    )


def build_system_prompt(company_name: str, call_flow: dict[str, Any]) -> str:
    """Assemble a system prompt for Vapi from our call_flow_draft JSON.

    The call_flow JSON has: greeting, questions[], boundaries[], handoff_method,
    handoff_template, after_hours_note.
    """
    questions = call_flow.get("questions") or []
    boundaries = call_flow.get("boundaries") or []
    after_hours_note = call_flow.get("after_hours_note") or ""

    questions_block = "\n".join(f"- {q}" for q in questions) or "- (no specific questions)"
    boundaries_block = "\n".join(f"- {b}" for b in boundaries) or "- (no specific boundaries)"

    return f"""You are the after-hours / overflow AI receptionist for {company_name}, a pest control company.
Your ONLY job: pick up a missed call, gather lead information, reassure the caller,
promise a callback, and end the call. You do NOT solve their pest problem.

GATHER (ask each, but conversationally — don't sound like a checklist):
{questions_block}

HARD RULES — these are non-negotiable:
{boundaries_block}

AFTER-HOURS LANGUAGE:
{after_hours_note}

CONVERSATION STYLE:
- Warm, calm, human. Short sentences. Pause to let the caller speak.
- If the caller is upset, acknowledge it explicitly before asking anything.
- If the caller is in distress (severe infestation, allergic reaction, child or
  baby involved), promise a callback within 30 minutes during business hours,
  or first thing the next business day.
- NEVER quote prices. NEVER guarantee an appointment, outcome, or treatment.
- NEVER diagnose the pest issue. Just gather what they're seeing.
- If asked something you can't answer, say: "Great question — I'll have the team
  cover that on the callback."

WHEN YOU HAVE WHAT YOU NEED:
Confirm the callback number out loud, summarize the issue in one sentence, then
politely close the call.

You are NOT human. If asked, say honestly: "I'm an answering assistant for {company_name},
but everything you tell me goes straight to the team."
""".strip()


def create_assistant(*, company_name: str, call_flow: dict[str, Any], server_url: str | None = None) -> dict[str, Any]:
    """Create a Vapi assistant from a customer's approved call flow.

    Returns the full assistant dict (includes 'id').
    """
    s = get_settings()
    system_prompt = build_system_prompt(company_name, call_flow)
    greeting = (call_flow.get("greeting") or
                f"Hi, thanks for calling {company_name} — I'm the after-hours assistant.")

    payload: dict[str, Any] = {
        "name": f"GlowBridge — {company_name}",
        "firstMessage": greeting,
        "model": {
            "provider": s.vapi_model_provider,
            "model": s.vapi_model_name,
            "messages": [{"role": "system", "content": system_prompt}],
            "temperature": 0.4,
        },
        "voice": {
            "provider": s.vapi_voice_provider,
            "voiceId": s.vapi_voice_id,
        },
        "endCallMessage": DEFAULT_END_MESSAGE,
        "endCallFunctionEnabled": True,
        "recordingEnabled": True,
        "silenceTimeoutSeconds": 25,
        "maxDurationSeconds": 600,
    }
    if server_url:
        payload["serverUrl"] = server_url
        if s.vapi_webhook_secret:
            payload["serverUrlSecret"] = s.vapi_webhook_secret

    with _client() as c:
        r = c.post("/assistant", json=payload)
        r.raise_for_status()
        return r.json()


def create_phone_number(*, assistant_id: str, area_code: str | None = None) -> dict[str, Any]:
    """Provision a Vapi-managed US phone number bound to an assistant."""
    s = get_settings()
    payload: dict[str, Any] = {
        "provider": s.vapi_phone_provider,
        "assistantId": assistant_id,
        "name": f"glowbridge-{assistant_id[:8]}",
    }
    if area_code:
        payload["areaCode"] = area_code

    with _client() as c:
        r = c.post("/phone-number", json=payload)
        r.raise_for_status()
        return r.json()


def update_assistant(assistant_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _client() as c:
        r = c.patch(f"/assistant/{assistant_id}", json=patch)
        r.raise_for_status()
        return r.json()


def get_assistant(assistant_id: str) -> dict[str, Any]:
    with _client() as c:
        r = c.get(f"/assistant/{assistant_id}")
        r.raise_for_status()
        return r.json()


def get_call(call_id: str) -> dict[str, Any]:
    with _client() as c:
        r = c.get(f"/call/{call_id}")
        r.raise_for_status()
        return r.json()
