from fastapi import APIRouter
from app.config import settings
from app.database import check_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    db_ok = check_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
    }


@router.get("/system/info")
def system_info():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "deployment_mode": settings.deployment_mode,
    }
