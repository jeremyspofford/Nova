"""API endpoints for linked accounts — maps platform identities to Nova users."""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .auth import UserDep
from .linked_accounts import (
    resolve_platform_account,
    get_active_conversation_for_user,
    auto_link,
    create_link,
    list_links,
    delete_link,
    generate_link_code,
    redeem_link_code,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/linked-accounts", tags=["linked-accounts"])

# --- Models ---

class ResolveRequest(BaseModel):
    platform: str
    platform_id: str

class ResolveResponse(BaseModel):
    user_id: str
    conversation_id: str
    display_name: str

class AutoLinkRequest(BaseModel):
    platform: str
    platform_id: str
    platform_username: str | None = None

class RedeemRequest(BaseModel):
    code: str
    platform: str
    platform_id: str
    platform_username: str | None = None

# --- Service-auth endpoints (bridge calls these) ---

def _require_service_secret(request: Request):
    """Validate X-Service-Secret header for bridge-to-orchestrator trust."""
    from .config import settings
    secret = request.headers.get("X-Service-Secret", "")
    if not secret or secret != settings.bridge_service_secret:
        raise HTTPException(status_code=403, detail="Invalid service secret")

@router.post("/resolve", response_model=ResolveResponse)
async def resolve_endpoint(req: ResolveRequest, request: Request):
    """Map platform + platform_id to user_id + conversation_id. Used by bridge."""
    _require_service_secret(request)
    account = await resolve_platform_account(req.platform, req.platform_id)
    if not account:
        raise HTTPException(status_code=404, detail="No linked account found")
    conv = await get_active_conversation_for_user(str(account["user_id"]))
    return ResolveResponse(
        user_id=str(account["user_id"]),
        conversation_id=str(conv["id"]),
        display_name=account.get("display_name") or account.get("email", ""),
    )

@router.post("/auto-link")
async def auto_link_endpoint(req: AutoLinkRequest, request: Request):
    """Auto-link when one user exists with no link. Used by bridge."""
    _require_service_secret(request)
    result = await auto_link(req.platform, req.platform_id, req.platform_username)
    if not result:
        raise HTTPException(
            status_code=409,
            detail="Auto-link not available. Multiple users exist or a link already exists."
        )
    return result

@router.post("/redeem")
async def redeem_endpoint(req: RedeemRequest, request: Request):
    """Validate a link code and create the binding. Used by bridge /link command."""
    _require_service_secret(request)
    result = await redeem_link_code(req.code, req.platform, req.platform_id, req.platform_username)
    if not result:
        raise HTTPException(status_code=404, detail="Invalid or expired link code")
    return result

# --- User-auth endpoints (dashboard calls these) ---

@router.get("")
async def list_links_endpoint(user: UserDep):
    """List all linked accounts (admin sees all, regular user sees own)."""
    return await list_links()

@router.delete("/{link_id}")
async def delete_link_endpoint(link_id: str, user: UserDep):
    """Unlink a platform account."""
    deleted = await delete_link(link_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Linked account not found")
    return {"status": "unlinked"}

@router.post("/link-code")
async def generate_link_code_endpoint(user: UserDep):
    """Generate a 6-char link code for the authenticated user."""
    code = await generate_link_code(str(user.id))
    return {"code": code, "ttl_seconds": 600}
