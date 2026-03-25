import os


class Settings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8000")
    llm_gateway_url: str = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8001")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/8")
    admin_secret: str = os.getenv("NOVA_ADMIN_SECRET", "nova-admin-secret-change-me")
    credential_master_key: str = os.getenv("CREDENTIAL_MASTER_KEY", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_crawl_pages: int = int(os.getenv("MAX_CRAWL_PAGES", "50"))
    max_llm_calls_per_crawl: int = int(os.getenv("MAX_LLM_CALLS_PER_CRAWL", "60"))
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "300"))
    port: int = int(os.getenv("PORT", "8120"))


settings = Settings()
