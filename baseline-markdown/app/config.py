from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Markdown source directory (scanned on startup)
    markdown_dir: str = "/data/markdown"

    # LLM Gateway (for embedding generation)
    llm_gateway_url: str = "http://llm-gateway:8001"

    # Service
    port: int = 8005
    log_level: str = "INFO"


settings = Settings()
