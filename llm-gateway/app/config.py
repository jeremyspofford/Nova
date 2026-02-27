from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://redis:6379/1"
    response_cache_ttl: int = 300  # 5 minutes for identical requests

    # Ollama (development)
    ollama_base_url: str = "http://ollama:11434"
    default_chat_model: str = "llama3.2"
    default_embed_model: str = "nomic-embed-text"

    # ── Per-provider default models — override in .env to swap models ──────────
    # These control which model a provider uses when no explicit model is given.
    # e.g. set DEFAULT_CEREBRAS_MODEL=cerebras/llama-3.1-8b for a faster/cheaper model
    default_ollama_model: str = "llama3.2"
    default_groq_model: str = "groq/llama-3.3-70b-versatile"
    default_gemini_model: str = "gemini/gemini-2.5-flash"
    default_cerebras_model: str = "cerebras/llama3.1-8b"   # llama3.3-70b was retired
    default_openrouter_model: str = "openrouter/meta-llama/llama-3.1-8b-instruct:free"
    default_github_model: str = "github/gpt-4o-mini"
    default_claude_max_model: str = "claude-max/claude-sonnet-4-6"
    default_chatgpt_model: str = "chatgpt/gpt-4o"

    # Anthropic (production) — api.anthropic.com API key, separate from claude.ai subscription
    anthropic_api_key: str = ""

    # OpenAI
    openai_api_key: str = ""

    # ── Free-tier providers (no credit card required) ──────────────────────────
    # Groq: 14,400 req/day free — get key at console.groq.com
    groq_api_key: str = ""

    # Google AI Studio: 250 req/day free — get key at aistudio.google.com
    # Also supports ADC: run `gcloud auth application-default login`
    # and set gemini_use_adc=true — no API key needed
    gemini_api_key: str = ""
    gemini_use_adc: bool = False  # Use gcloud Application Default Credentials

    # Cerebras: 1M tokens/day free — get key at cloud.cerebras.ai
    cerebras_api_key: str = ""

    # OpenRouter: free models available — get key at openrouter.ai
    openrouter_api_key: str = ""

    # GitHub Models: 50-150 req/day free — use your GitHub PAT
    # https://github.com/marketplace/models
    github_token: str = ""

    # ── Subscription providers (quota from existing subscriptions) ─────────────
    # Claude Max/Pro subscription — no api.anthropic.com billing
    # Get token: run `claude setup-token` → produces sk-ant-oat01-...
    # Auto-read from ~/.claude/.credentials.json (Linux) or macOS Keychain
    claude_code_oauth_token: str = ""

    # ChatGPT Plus/Pro subscription — no api.openai.com billing
    # Auto-read from ~/.codex/auth.json after `codex login`
    # Or extract manually: jq -r '.tokens.access_token' ~/.codex/auth.json
    chatgpt_access_token: str = ""
    chatgpt_token_dir: str = ""  # defaults to ~/.codex

    # Cost tracking
    track_costs: bool = True

    service_host: str = "0.0.0.0"
    service_port: int = 8001
    log_level: str = "INFO"


settings = Settings()
