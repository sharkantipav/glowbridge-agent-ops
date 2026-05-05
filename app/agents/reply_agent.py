from app.agents.base import BaseAgent


class ReplyAgent(BaseAgent):
    name = "reply"
    ESCALATE = {"interested", "wants call", "angry", "legal", "unsubscribe", "low_confidence"}

    def classify(self, body: str) -> str:
        prompt = (
            "Classify this email into one label exactly: interested, not interested, asked price, "
            "asked how it works, wants call, objection, angry, unsubscribe, legal, low_confidence. "
            f"Email: {body}"
        )
        return self.llm_text(prompt, max_tokens=10).lower().strip()
