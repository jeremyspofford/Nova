import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.config import settings as _settings
from app.database import get_db
from app.models.llm_provider import LLMProviderProfile
from app.schemas.llm_provider import LLMRouteRequest, LLMRouteResponse
from app import llm_client

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/models")
def list_models():
    """Return available models from the configured Ollama instance."""
    if not _settings.ollama_base_url:
        raise HTTPException(503, detail="Ollama not configured (OLLAMA_BASE_URL not set)")
    try:
        resp = httpx.get(f"{_settings.ollama_base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
    except Exception as exc:
        raise HTTPException(502, detail=f"Could not reach Ollama: {exc}")
    return {"models": models}


class ProviderModelUpdate(BaseModel):
    model_ref: str


@router.patch("/providers/local", status_code=200)
def update_local_model(body: ProviderModelUpdate, db: Session = Depends(get_db)):
    """Update the model_ref for the local (Ollama) provider."""
    provider = (
        db.query(LLMProviderProfile)
        .filter(LLMProviderProfile.provider_type == "local", LLMProviderProfile.enabled == True)  # noqa: E712
        .first()
    )
    if not provider:
        raise HTTPException(404, detail="No enabled local provider found")
    provider.model_ref = body.model_ref
    db.commit()
    return {"provider_id": provider.id, "model_ref": provider.model_ref}


@router.get("/providers/local")
def get_local_provider(db: Session = Depends(get_db)):
    """Return the current local (Ollama) provider config."""
    provider = (
        db.query(LLMProviderProfile)
        .filter(LLMProviderProfile.provider_type == "local", LLMProviderProfile.enabled == True)  # noqa: E712
        .first()
    )
    if not provider:
        raise HTTPException(404, detail="No enabled local provider found")
    return {"id": provider.id, "name": provider.name, "provider_type": provider.provider_type,
            "model_ref": provider.model_ref, "enabled": provider.enabled}


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    providers = db.query(LLMProviderProfile).all()
    return {"providers": [
        {"id": p.id, "name": p.name, "provider_type": p.provider_type,
         "model_ref": p.model_ref, "enabled": p.enabled}
        for p in providers
    ]}


@router.get("/providers/{provider_id}")
def get_provider(provider_id: str, db: Session = Depends(get_db)):
    provider = db.query(LLMProviderProfile).filter(LLMProviderProfile.id == provider_id).first()
    if not provider:
        raise HTTPException(404, detail="Provider not found")
    return {"id": provider.id, "name": provider.name, "provider_type": provider.provider_type,
            "model_ref": provider.model_ref, "enabled": provider.enabled}


@router.post("/route", response_model=LLMRouteResponse)
def route_llm(body: LLMRouteRequest, db: Session = Depends(get_db)):
    messages = body.input.get("messages", [])
    try:
        result = llm_client.route(
            db,
            purpose=body.purpose,
            messages=messages,
            privacy_preference=body.privacy_preference,
        )
    except llm_client.NoProvidersError:
        raise HTTPException(
            503,
            detail="No LLM providers configured. Set OLLAMA_BASE_URL and OLLAMA_MODEL to configure a local provider.",
        )
    except llm_client.NoMatchingProvidersError:
        raise HTTPException(
            503,
            detail="No LLM providers available for the requested privacy preference.",
        )
    except llm_client.AllProvidersFailed as exc:
        raise HTTPException(502, detail=f"All LLM providers failed: {exc.last_error}")
    return LLMRouteResponse(
        provider_id=result.provider_id,
        model_ref=result.model_ref,
        output=result.output,
    )
