from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    nova_api_url: str
    loop_interval_seconds: int = 15
    cursor_file: str = "/app/state/cursor.json"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
