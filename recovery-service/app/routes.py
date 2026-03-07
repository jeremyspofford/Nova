"""Recovery service API routes."""

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .backup import create_backup, delete_backup, list_backups, list_checkpoints, restore_backup
from .compose_client import start_profiled_service, stop_profiled_service
from .config import settings
from .docker_client import check_container_status, get_container_logs, list_service_status, restart_all_services, restart_service
from .env_manager import add_compose_profile, patch_env, read_env, remove_compose_profile
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


# ── Env Management ────────────────────────────────────────────────────────────

@router.get("/api/v1/recovery/env")
async def get_env_vars(x_admin_secret: str = Header(default="")):
    """Read whitelisted env vars (secrets masked)."""
    _check_admin(x_admin_secret)
    return read_env()


class EnvPatchRequest(BaseModel):
    updates: dict[str, str]


@router.patch("/api/v1/recovery/env")
async def patch_env_vars(
    req: EnvPatchRequest,
    x_admin_secret: str = Header(default=""),
):
    """Update .env keys (whitelist enforced)."""
    _check_admin(x_admin_secret)
    try:
        return patch_env(req.updates)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Compose Profiles ─────────────────────────────────────────────────────────

PROFILE_MAP = {
    "cloudflare-tunnel": "cloudflared",
    "tailscale": "tailscale",
    "bridges": "chat-bridge",
}


class ComposeProfileRequest(BaseModel):
    profile: str
    action: str  # "start" or "stop"


@router.post("/api/v1/recovery/compose-profiles")
async def manage_compose_profile(
    req: ComposeProfileRequest,
    x_admin_secret: str = Header(default=""),
):
    """Add/remove a compose profile and start/stop its service."""
    _check_admin(x_admin_secret)
    if req.profile not in PROFILE_MAP:
        raise HTTPException(400, f"Unknown profile: {req.profile}. Valid: {list(PROFILE_MAP.keys())}")

    service = PROFILE_MAP[req.profile]
    if req.action == "start":
        add_compose_profile(req.profile)
        result = await start_profiled_service(req.profile, service)
    elif req.action == "stop":
        result = await stop_profiled_service(req.profile, service)
        remove_compose_profile(req.profile)
    else:
        raise HTTPException(400, "action must be 'start' or 'stop'")

    if not result["ok"]:
        raise HTTPException(500, result.get("error", "Compose operation failed"))
    return {"profile": req.profile, "service": service, "action": req.action, **result}


# ── Remote Access Status ─────────────────────────────────────────────────────

@router.get("/api/v1/recovery/remote-access/status")
async def get_remote_access_status(x_admin_secret: str = Header(default="")):
    """Container + config status for Cloudflare Tunnel and Tailscale."""
    _check_admin(x_admin_secret)
    env = read_env()
    cf_status = check_container_status("cloudflared")
    ts_status = check_container_status("tailscale")

    return {
        "cloudflare": {
            "configured": bool(env.get("CLOUDFLARE_TUNNEL_TOKEN")),
            "container": cf_status,
        },
        "tailscale": {
            "configured": bool(env.get("TAILSCALE_AUTHKEY")),
            "container": ts_status,
        },
    }


# ── Chat Integrations Status ─────────────────────────────────────────────────

@router.get("/api/v1/recovery/chat-integrations/status")
async def get_chat_integrations_status(x_admin_secret: str = Header(default="")):
    """Container + config status for chat bridge adapters (Telegram, Slack)."""
    _check_admin(x_admin_secret)
    env = read_env()
    bridge_status = check_container_status("chat-bridge")

    return {
        "telegram": {
            "configured": bool(env.get("TELEGRAM_BOT_TOKEN")),
            "container": bridge_status,
        },
        "slack": {
            "configured": bool(env.get("SLACK_BOT_TOKEN")),
            "container": bridge_status,
        },
        "container": bridge_status,
    }


# ── Diagnostics ────────────────────────────────────────────────────────────────

@router.get("/api/v1/recovery/diagnostics")
async def get_diagnostics(x_admin_secret: str = Header(default="")):
    """Aggregated diagnostics for AI troubleshooting: service health, logs, DB status."""
    _check_admin(x_admin_secret)
    from .db import get_pool
    import re

    services = list_service_status()
    checkpoints = list_checkpoints()

    # Collect logs from unhealthy/down services
    service_logs: dict[str, str] = {}
    for svc in services:
        if svc["status"] != "running" or svc["health"] not in ("healthy", "none"):
            service_logs[svc["service"]] = get_container_logs(svc["service"], tail=50)

    # DB connectivity
    db_info: dict = {}
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            db_size = await conn.fetchval(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )
            db_info = {"connected": True, "size": db_size}
    except Exception as e:
        db_info = {"connected": False, "error": str(e)}

    # Extract error patterns from logs
    error_patterns: list[str] = []
    for svc_name, logs in service_logs.items():
        for line in logs.splitlines()[-50:]:
            if re.search(r"(?i)(error|exception|traceback|fatal|panic|crash)", line):
                error_patterns.append(f"[{svc_name}] {line.strip()[-200:]}")

    return {
        "services": services,
        "service_logs": service_logs,
        "database": db_info,
        "checkpoints": {
            "count": len(checkpoints),
            "latest": checkpoints[0] if checkpoints else None,
        },
        "error_patterns": error_patterns[:30],
    }


# ── Troubleshoot ──────────────────────────────────────────────────────────────

from .troubleshoot import TroubleshootRequest, troubleshoot_chat

@router.post("/api/v1/recovery/troubleshoot/chat")
async def troubleshoot_endpoint(
    req: TroubleshootRequest,
    x_admin_secret: str = Header(default=""),
):
    """AI-powered troubleshooting chat — calls an external LLM directly."""
    _check_admin(x_admin_secret)
    return await troubleshoot_chat(req)


# ── Factory Reset ──────────────────────────────────────────────────────────────

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
