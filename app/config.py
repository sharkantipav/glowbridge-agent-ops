import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Local-dev nicety: if a .env file exists in the project root, let it override
# any stale OS environment variables. Prevents the classic "I set MY_KEY in .env
# but Windows has an empty MY_KEY env var from years ago" footgun. In production
# (Railway/Fly), no .env file exists, so this no-ops and OS env wins as expected.
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Anthropic
    anthropic_api_key: str
    llm_model_fast: str = "claude-haiku-4-5-20251001"
    llm_model_smart: str = "claude-sonnet-4-6"

    # Supabase
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str | None = None

    # Gmail
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    gmail_from_address: str = "noreply@glowbridge.ai"
    gmail_from_name: str = "GlowBridge"

    # Stripe
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_setup: str | None = None
    stripe_price_monthly: str | None = None

    # Browserbase
    browserbase_api_key: str | None = None
    browserbase_project_id: str | None = None

    # Search
    brave_api_key: str | None = None
    tavily_api_key: str | None = None

    # Admin
    admin_token: str
    operator_email: str = "charles@glowbridge.ai"

    # App
    app_env: Literal["development", "staging", "production"] = "development"
    app_base_url: str = "http://localhost:8000"
    timezone: str = "America/New_York"

    # Safety toggles — default OFF
    enable_outreach_send: bool = False
    enable_reply_autoreply: bool = False
    enable_social_autopost: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
