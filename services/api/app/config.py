from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deployment_mode: str = "local"
    service_name: str = "nova-api"
    version: str = "0.1.0"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
