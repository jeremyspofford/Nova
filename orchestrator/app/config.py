from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://redis:6379/2"
    memory_service_url: str = "http://memory-service:8002"
    llm_gateway_url: str = "http://llm-gateway:8001"

    default_model: str = "auto"
    default_system_prompt: str = (
        "You are a helpful AI assistant with persistent memory. "
        "You remember previous conversations and can use tools to help users."
    )
    # The canonical agent that is auto-created (or adopted) on every startup.
    # Duplicates with the same name+model are pruned automatically.
    primary_agent_name: str = "Nova"

    # Context window budgets (from Part 3 token allocation research)
    context_system_pct: float = 0.10
    context_tools_pct: float = 0.15
    context_memory_pct: float = 0.40
    context_history_pct: float = 0.20
    context_working_pct: float = 0.15
    context_compaction_threshold: float = 0.80  # Trigger at 80% usage

    service_host: str = "0.0.0.0"
    service_port: int = 8000
    log_level: str = "INFO"

    # Phase 2: Postgres connection for api_keys + usage_events tables
    database_url: str = "postgresql+asyncpg://nova:nova_dev_password@postgres:5432/nova"
    # Phase 2: Shared secret for admin key-management endpoints (X-Admin-Secret header)
    nova_admin_secret: str = "nova-admin-secret-change-me"
    # Phase 2: Set False in .env during local dev to skip API key validation entirely
    require_auth: bool = True
    cors_allowed_origins: str = "http://localhost:3001,http://localhost:5173,http://localhost:8080"

    # Phase 3: Code & Terminal Tools
    workspace_root: str = "/workspace"
    shell_timeout_seconds: int = 30
    # Sandbox tier: workspace | nova | host | isolated (Phase 3b)
    shell_sandbox: str = "workspace"
    nova_root: str = "/nova"

    # Phase 4: Task Queue + Failure Recovery
    # Running tasks write a heartbeat every N seconds
    task_heartbeat_interval_seconds: int = 30
    # Reaper wakes up every N seconds to scan for stale tasks
    reaper_interval_seconds: int = 60
    # A task is considered stale if no heartbeat for this many seconds
    task_stale_seconds: int = 150
    # Default maximum retries before a task goes to dead letter
    task_default_max_retries: int = 2
    # Tasks stuck in queued state longer than this are re-pushed
    stale_queued_seconds: int = 120
    # Extra buffer before declaring an agent session timed out
    session_timeout_buffer_seconds: int = 30
    # Utility model (used for conversation titles, etc.)
    session_summary_model: str = "claude-haiku-4-5-20251001"
    # Redis heartbeat key TTL — should be < task_stale_seconds
    task_heartbeat_ttl_seconds: int = 120
    # Default pod name used when no routing match is found
    default_pod_name: str = "Quartet"

    # Phase 4b: Memory context pre-warming for active chat sessions
    memory_prewarm_enabled: bool = True
    memory_prewarm_ttl_seconds: int = 60
    # Maximum number of pipeline executions that can run concurrently
    pipeline_max_concurrent: int = 5

    # Trusted networks — comma-separated CIDRs that bypass auth (treated as admin)
    # Default includes RFC1918 private ranges, Tailscale CGNAT, and localhost
    trusted_networks: str = "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,::1/128"
    # Header containing the real client IP when behind a trusted reverse proxy
    # e.g. CF-Connecting-IP (Cloudflare), X-Real-IP (nginx), X-Forwarded-For
    trusted_proxy_header: str = ""

    # User auth
    jwt_secret: str = ""  # Auto-generated if empty (stored in platform_config)
    google_client_id: str = ""
    google_client_secret: str = ""
    registration_mode: str = "invite"  # 'open' | 'invite' | 'admin'


settings = Settings()
