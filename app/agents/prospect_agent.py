from app.agents.base import BaseAgent


class ProspectAgent(BaseAgent):
    name = "prospect"

    def run(self, limit: int = 25) -> list[dict]:
        prompt = (
            "Return JSON array of pest control companies in NJ, NY, PA, CT with keys: "
            "company_name, website, city, state, phone, email, contact_name, lead_score (1-10). "
            f"Return {limit} unique companies only."
        )
        text = self.llm_text(prompt, max_tokens=1800)
        # In production, add strict JSON parsing + browserbase verification.
        return [{"raw": text}]
