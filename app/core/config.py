from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_port: int = 8000
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_from_email: str = ""

    browserbase_api_key: str = ""
    browserbase_project_id: str = ""
    stagehand_api_key: str = ""

    charles_email: str = "charles@glowbridge.ai"
    setup_form_url: str = "https://example.com/setup-form"
    frontend_base_url: str = "http://localhost:8000"


settings = Settings()
