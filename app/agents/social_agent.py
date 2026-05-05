from app.agents.base import BaseAgent


class SocialAgent(BaseAgent):
    name = "social"

    def generate_daily(self) -> str:
        prompt = (
            "Generate: 2 X posts, 1 TikTok/Reels script, 1 Instagram caption, 1 Reddit research question "
            "for pest control missed-call operations. No invented customers/revenue/case studies."
        )
        return self.llm_text(prompt, max_tokens=500)
