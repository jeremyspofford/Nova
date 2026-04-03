"""
Baseline pgvector service configuration.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://nova:nova@postgres:5432/nova"
    llm_gateway_url: str = "http://llm-gateway:8001"
    port: int = 8003
    log_level: str = "INFO"

    # Embedding model to request from llm-gateway
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768

    # Retrieval defaults
    default_top_k: int = 10

    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 100

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
