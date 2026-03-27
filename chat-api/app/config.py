from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    orchestrator_url: str = "http://orchestrator:8000"
    redis_url: str = "redis://redis:6379/3"

    # Default agent — created on first connection if no agent_id provided
    default_agent_name: str = "Nova"
    default_model: str = "auto"

    require_auth: bool = True
    cors_allowed_origins: str = "http://localhost:3001,http://localhost:5173,http://localhost:8080"

    # WebSocket limits
    ws_max_connections: int = 100
    ws_max_per_ip: int = 10
    ws_max_history: int = 200  # Max messages retained in conversation_history per connection

    service_host: str = "0.0.0.0"
    service_port: int = 8080
    log_level: str = "INFO"


settings = Settings()
