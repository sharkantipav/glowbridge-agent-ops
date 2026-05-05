from app.agents.base import BaseAgent


class CustomerAgent(BaseAgent):
    name = "customer"

    def draft_call_flow(self, company_name: str) -> str:
        prompt = (
            "Draft concise AI receptionist call flow for pest control. Never claim guaranteed bookings/pricing. "
            f"Company: {company_name}"
        )
        return self.llm_text(prompt, max_tokens=260)
