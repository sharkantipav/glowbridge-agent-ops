from app.agents.base import BaseAgent


class OutreachAgent(BaseAgent):
    name = "outreach"

    def draft_email(self, lead: dict) -> str:
        prompt = (
            "Write a personalized outreach email under 90 words for GlowBridge missed-call AI receptionist. "
            "Never promise guaranteed revenue, guaranteed bookings, or quoting pest-control prices. "
            f"Lead: {lead}"
        )
        return self.llm_text(prompt, max_tokens=180)

    def can_auto_send(self, lead: dict, text: str) -> tuple[bool, str]:
        if lead.get("lead_score", 0) < 8:
            return False, "score_below_8"
        if not lead.get("email"):
            return False, "missing_email"
        words = len(text.split())
        if words >= 100:
            return False, "too_long"
        lowered = text.lower()
        blocked = ["guaranteed revenue", "guaranteed booking", "we quote pest prices"]
        if any(p in lowered for p in blocked):
            return False, "unsafe_claim"
        return True, "ok"
