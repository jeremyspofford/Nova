"""Cortex service configuration — reads from environment variables."""
import os


class Settings:
    port: int = 8100

    # Postgres (shared with orchestrator — same database)
    pg_host: str = os.getenv("POSTGRES_HOST", "postgres")
    pg_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    pg_user: str = os.getenv("POSTGRES_USER", "nova")
    pg_password: str = os.getenv("POSTGRES_PASSWORD", "nova_dev_password")
    pg_database: str = os.getenv("POSTGRES_DB", "nova")

    # Redis DB 5 (dedicated to cortex)
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/5")

    # Inter-service URLs
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
    llm_gateway_url: str = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8001")
    memory_service_url: str = os.getenv("MEMORY_SERVICE_URL", "http://memory-service:8002")
    recovery_url: str = os.getenv("RECOVERY_URL", "http://recovery:8888")

    # Auth — cortex uses its own API key to talk to orchestrator
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")

    # Thinking cycle
    cycle_interval_seconds: int = int(os.getenv("CORTEX_CYCLE_INTERVAL", "300"))
    enabled: bool = os.getenv("CORTEX_ENABLED", "true").lower() == "true"

    # Budget
    daily_budget_usd: float = float(os.getenv("CORTEX_DAILY_BUDGET_USD", "5.00"))

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def pg_dsn(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"


settings = Settings()
