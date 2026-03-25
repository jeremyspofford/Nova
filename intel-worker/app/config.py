import os


class Settings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/6")
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "60"))
    port: int = int(os.getenv("PORT", "8110"))


settings = Settings()
