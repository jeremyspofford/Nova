from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.llm_provider import LLMRouteRequest, LLMRouteResponse
from app import llm_client

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers")
def list_providers():
    raise NotImplementedError


@router.get("/providers/{provider_id}")
def get_provider(provider_id: str):
    raise NotImplementedError


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
