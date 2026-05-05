from app.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    name = "research"

    def run(self, company: dict) -> dict:
        prompt = (
            "Given this pest company data, infer if emergency service/after-hours/call-only booking appears. "
            "Create a one-sentence pain signal focused on missed calls and slow responses. Company: "
            f"{company}"
        )
        summary = self.llm_text(prompt, max_tokens=220)
        return {"company_id": company.get("id"), "pain_signal": summary}
