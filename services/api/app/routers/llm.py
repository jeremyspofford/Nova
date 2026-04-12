from fastapi import APIRouter
from app.schemas.llm_provider import LLMRouteRequest

router = APIRouter(prefix="/llm", tags=["llm"])

@router.get("/providers")
def list_providers():
    raise NotImplementedError

@router.get("/providers/{provider_id}")
def get_provider(provider_id: str):
    raise NotImplementedError

@router.post("/route")
def route_llm(body: LLMRouteRequest):
    raise NotImplementedError
