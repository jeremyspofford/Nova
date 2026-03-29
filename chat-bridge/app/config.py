from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    orchestrator_url: str = "http://orchestrator:8000"
    redis_url: str = "redis://redis:6379/4"

    # API key for authenticating with orchestrator
    nova_api_key: str = ""

    # Bridge service secret shared with orchestrator
    bridge_service_secret: str = ""

    # Admin secret for authenticated management endpoints (shared with dashboard)
    nova_admin_secret: str = ""

    # Default agent settings for bridge sessions
    default_agent_name: str = "Nova"
    default_model: str = "auto"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # Slack (Phase 2)
    slack_bot_token: str = ""
    slack_app_token: str = ""

    service_host: str = "0.0.0.0"
    service_port: int = 8090
    log_level: str = "INFO"

    require_auth: bool = True


settings = Settings()
