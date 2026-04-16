from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    deployment_mode: str = "local"
    service_name: str = "nova-api"
    version: str = "0.1.0"
    ollama_base_url: str = ""
    ollama_model: str = "gemma3:4b"
    ha_base_url: str = ""
    ha_token: str = ""
    nova_workspace_dir: str = Field(default="~", validation_alias="NOVA_WORKSPACE_DIR")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
