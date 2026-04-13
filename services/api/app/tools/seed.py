"""
Startup seeding for tools and LLM providers.
Called from main.py lifespan on every startup (upsert — safe to re-run).
"""
from sqlalchemy.orm import Session
from app.models.llm_provider import LLMProviderProfile


def seed_llm_providers(db: Session, settings) -> None:
    """Upsert the Ollama local provider if OLLAMA_BASE_URL is set."""
    if not settings.ollama_base_url:
        return

    provider = db.query(LLMProviderProfile).filter(
        LLMProviderProfile.id == "ollama-local"
    ).first()

    if provider:
        provider.endpoint_ref = settings.ollama_base_url + "/v1"
        provider.model_ref = settings.ollama_model
        provider.enabled = True
    else:
        provider = LLMProviderProfile(
            id="ollama-local",
            name="Ollama Local",
            provider_type="local",
            endpoint_ref=settings.ollama_base_url + "/v1",
            model_ref=settings.ollama_model,
            enabled=True,
            supports_tools=False,
            supports_streaming=False,
            privacy_class="local_only",
            cost_class="low",
            latency_class="medium",
        )
        db.add(provider)

    db.commit()


def seed_tools(db: Session) -> None:
    """Placeholder — full implementation in Task 5."""
    pass
