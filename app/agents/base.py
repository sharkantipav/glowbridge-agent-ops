from openai import OpenAI

from app.core.config import settings


class BaseAgent:
    name = "base"

    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)

    def llm_text(self, prompt: str, max_tokens: int = 300) -> str:
        response = self.client.responses.create(
            model=settings.openai_model,
            input=prompt,
            max_output_tokens=max_tokens,
        )
        return response.output_text.strip()
