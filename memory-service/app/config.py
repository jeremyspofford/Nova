from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://nova:nova@postgres:5432/nova"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://redis:6379/0"
    redis_working_memory_ttl: int = 3600       # 1 hour hot cache
    redis_search_cache_ttl: int = 30           # 30s search result cache
    redis_embedding_cache_ttl: int = 86400     # 24h embedding cache

    # LLM Gateway (for embedding generation)
    llm_gateway_url: str = "http://llm-gateway:8001"
    embedding_model: str = "nomic-embed-text"  # Ollama default
    embedding_dimensions: int = 768

    # Cleanup
    working_memory_cleanup_interval_seconds: int = 300

    # Service
    service_host: str = "0.0.0.0"
    service_port: int = 8002
    log_level: str = "INFO"


settings = Settings()
