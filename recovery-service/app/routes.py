"""Recovery service API routes."""

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .backup import create_backup, delete_backup, list_backups, restore_backup
from .config import settings
from .docker_client import list_service_status, restart_all_services, restart_service
from .factory_reset import factory_reset, get_categories

logger = logging.getLogger("nova.recovery")

router = APIRouter()


# ── Auth ───────────────────────────────────────────────────────────────────────

def _check_admin(x_admin_secret: str = Header(default="")):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(401, "Invalid admin secret")


# ── Health ─────────────────────────────────────────────────────────────────────

@router.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "recovery"}


@router.get("/health/ready")
async def health_ready():
    from .db import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "degraded", "db": str(e)}


# ── Overview / Dashboard ───────────────────────────────────────────────────────

@router.get("/api/v1/recovery/status")
async def get_overview():
    """Rich status overview: service health, DB stats, backup info."""
    from .db import get_pool

    services = list_service_status()
    backups = list_backups()

    up = sum(1 for s in services if s["status"] == "running" and s["health"] in ("healthy", "none"))
    down = sum(1 for s in services if s["status"] != "running" or s["health"] not in ("healthy", "none", "unknown"))
    total = len(services)

    # DB stats
    db_info: dict = {}
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            db_size = await conn.fetchval(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )
            table_count = await conn.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
            db_info = {"connected": True, "size": db_size, "table_count": table_count}
    except Exception as e:
        db_info = {"connected": False, "error": str(e)}

    return {
        "services": {
            "up": up,
            "down": down,
            "total": total,
            "details": services,
        },
        "database": db_info,
        "backups": {
            "count": len(backups),
            "latest": backups[0] if backups else None,
            "total_size_bytes": sum(b["size_bytes"] for b in backups),
        },
    }


# ── Service Status ─────────────────────────────────────────────────────────────

@router.get("/api/v1/recovery/services")
async def get_services():
    """List all Nova service containers and their status."""
    return list_service_status()


@router.post("/api/v1/recovery/services/{service_name}/restart")
async def restart_service_endpoint(
    service_name: str,
    x_admin_secret: str = Header(default=""),
):
    _check_admin(x_admin_secret)
    result = restart_service(service_name)
    if not result["ok"]:
        raise HTTPException(400, result.get("error", "Restart failed"))
    return result


@router.post("/api/v1/recovery/services/restart-all")
async def restart_all_endpoint(x_admin_secret: str = Header(default="")):
    _check_admin(x_admin_secret)
    return restart_all_services()


# ── Backups ────────────────────────────────────────────────────────────────────

@router.get("/api/v1/recovery/backups")
async def get_backups():
    """List available backups."""
    return list_backups()


@router.post("/api/v1/recovery/backups")
async def create_backup_endpoint(x_admin_secret: str = Header(default="")):
    """Create a new backup."""
    _check_admin(x_admin_secret)
    try:
        return await create_backup()
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/api/v1/recovery/backups/{filename}/restore")
async def restore_backup_endpoint(
    filename: str,
    x_admin_secret: str = Header(default=""),
):
    """Restore from a specific backup."""
    _check_admin(x_admin_secret)
    try:
        return await restore_backup(filename)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.delete("/api/v1/recovery/backups/{filename}")
async def delete_backup_endpoint(
    filename: str,
    x_admin_secret: str = Header(default=""),
):
    """Delete a specific backup."""
    _check_admin(x_admin_secret)
    try:
        return delete_backup(filename)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))


# ── Factory Reset ──────────────────────────────────────────────────────────────

@router.get("/api/v1/recovery/factory-reset/categories")
async def get_reset_categories():
    """List data categories available for factory reset."""
    return get_categories()


class FactoryResetRequest(BaseModel):
    keep: list[str] = []
    confirm: str  # Must be "RESET" to proceed


@router.post("/api/v1/recovery/factory-reset")
async def factory_reset_endpoint(
    req: FactoryResetRequest,
    x_admin_secret: str = Header(default=""),
):
    """Factory reset — wipe data categories not in the 'keep' list."""
    _check_admin(x_admin_secret)
    if req.confirm != "RESET":
        raise HTTPException(400, "Confirmation required: set confirm to 'RESET'")
    result = await factory_reset(keep=set(req.keep))
    return result
