import httpx
from fastapi import APIRouter
from app.database import check_db
from app.config import settings

router = APIRouter(tags=["health"])


def _check_model_ready() -> bool:
    if not settings.ollama_base_url:
        return False
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        if not resp.is_success:
            return False
        tags = resp.json().get("models", [])
        return any(m.get("name", "").startswith(settings.ollama_model.split(":")[0]) for m in tags)
    except Exception:
        return False


@router.get("/health")
def health():
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "model_ready": _check_model_ready(),
    }
