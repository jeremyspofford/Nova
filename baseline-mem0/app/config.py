"""
Baseline Mem0 wrapper — configuration.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ollama (primary embedding + LLM provider)
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_llm_model: str = "llama3.1:latest"
    embedding_dims: int = 768

    # LLM Gateway (fallback when Ollama is unavailable)
    llm_gateway_url: str = "http://llm-gateway:8001"

    # Mem0 storage
    mem0_data_dir: str = "/data/mem0"
    mem0_collection_name: str = "nova_benchmark"

    # Service
    port: int = 8004
    log_level: str = "INFO"


settings = Settings()
