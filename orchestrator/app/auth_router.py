"""Auth + conversation endpoints for user authentication and chat persistence."""
from __future__ import annotations

import asyncio
import logging
import secrets
from uuid import UUID

import bcrypt
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr

from app.auth import AdminDep, UserDep
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


# ── Request/Response models ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None
    invite_code: str | None = None

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

class UpdateProfileRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 min
    user: dict

class ConversationCreate(BaseModel):
    title: str | None = None

class ConversationUpdate(BaseModel):
    title: str | None = None
    is_archived: bool | None = None

class MessageImport(BaseModel):
    messages: list[dict]

class InviteCreate(BaseModel):
    email: str | None = None
    expires_in_hours: int | None = 72


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def _safe_user(user: dict) -> dict:
    """Strip sensitive fields from user dict before returning to client."""
    return {k: v for k, v in user.items() if k not in ("password_hash",)}


# ── Auth config (public) ────────────────────────────────────────────────────

@router.get("/api/v1/auth/providers")
async def get_auth_providers():
    """Public: what auth options are available."""
    from app.oauth import google_enabled
    from app.users import count_users
    user_count = await count_users()
    return {
        "google": google_enabled(),
        "registration_mode": settings.registration_mode,
        "has_users": user_count > 0,
    }


# ── Registration ─────────────────────────────────────────────────────────────

@router.post("/api/v1/auth/register", response_model=AuthResponse)
async def register(req: RegisterRequest):
    from app.users import create_user, get_user_by_email, count_users
    from app.jwt_auth import create_access_token, create_refresh_token

    # Check registration mode
    if settings.registration_mode == "admin":
        raise HTTPException(status_code=403, detail="Registration is disabled. Ask an admin to create your account.")

    if settings.registration_mode == "invite":
        if not req.invite_code:
            raise HTTPException(status_code=400, detail="Invite code required")
        # Validate invite code
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            invite = await conn.fetchrow(
                "SELECT id, email, used_by FROM invite_codes "
                "WHERE code = $1 AND used_by IS NULL AND (expires_at IS NULL OR expires_at > NOW())",
                req.invite_code,
            )
        if not invite:
            raise HTTPException(status_code=400, detail="Invalid or expired invite code")
        if invite["email"] and invite["email"].lower() != req.email.lower():
            raise HTTPException(status_code=400, detail="This invite is for a different email address")

    # Check if email is taken
    existing = await get_user_by_email(req.email.lower())
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    if not req.password or len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # First user becomes admin
    user_count = await count_users()
    is_admin = user_count == 0

    password_hash = _hash_password(req.password)
    user = await create_user(
        email=req.email.lower(),
        password_hash=password_hash,
        display_name=req.display_name or req.email.split("@")[0],
        is_admin=is_admin,
    )

    # Mark invite as used
    if settings.registration_mode == "invite" and req.invite_code:
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE invite_codes SET used_by = $1, used_at = NOW() WHERE code = $2",
                UUID(user["id"]), req.invite_code,
            )

    access = create_access_token(user["id"], user["email"], user["is_admin"])
    refresh = await create_refresh_token(user["id"])

    return AuthResponse(
        access_token=access,
        refresh_token=refresh,
        user=_safe_user(user),
    )


# ── Login ────────────────────────────────────────────────────────────────────

@router.post("/api/v1/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    from app.users import get_user_by_email
    from app.jwt_auth import create_access_token, create_refresh_token

    user = await get_user_by_email(req.email.lower())
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access = create_access_token(user["id"], user["email"], user["is_admin"])
    refresh = await create_refresh_token(user["id"])

    return AuthResponse(
        access_token=access,
        refresh_token=refresh,
        user=_safe_user(user),
    )


# ── Token refresh ────────────────────────────────────────────────────────────

@router.post("/api/v1/auth/refresh", response_model=AuthResponse)
async def refresh_tokens(req: RefreshRequest):
    from app.jwt_auth import rotate_refresh_token

    result = await rotate_refresh_token(req.refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    access, refresh, user = result
    return AuthResponse(
        access_token=access,
        refresh_token=refresh,
        user=_safe_user(user),
    )


# ── Logout ───────────────────────────────────────────────────────────────────

@router.post("/api/v1/auth/logout", status_code=204)
async def logout(req: LogoutRequest):
    from app.jwt_auth import revoke_refresh_token
    await revoke_refresh_token(req.refresh_token)


# ── Profile ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/auth/me")
async def get_me(user: UserDep):
    from app.users import get_user_by_id
    full_user = await get_user_by_id(user.id)
    if not full_user:
        raise HTTPException(status_code=404, detail="User not found")
    return _safe_user(full_user)


@router.patch("/api/v1/auth/me")
async def update_me(req: UpdateProfileRequest, user: UserDep):
    from app.users import update_user
    updated = await update_user(user.id, display_name=req.display_name, avatar_url=req.avatar_url)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return _safe_user(updated)


@router.patch("/api/v1/auth/password", status_code=204)
async def change_password(req: ChangePasswordRequest, user: UserDep):
    """Change the authenticated user's password."""
    from app.users import get_user_by_id
    from app.db import get_pool

    full_user = await get_user_by_id(user.id)
    if not full_user or not full_user.get("password_hash"):
        raise HTTPException(status_code=400, detail="Cannot change password for OAuth-only accounts")

    if not _verify_password(req.current_password, full_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    new_hash = _hash_password(req.new_password)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash = $1, updated_at = NOW() WHERE id = $2",
            new_hash, UUID(user.id),
        )


# ── Google OAuth ─────────────────────────────────────────────────────────────

@router.get("/api/v1/auth/google")
async def google_auth(request: Request):
    from app.oauth import google_enabled, get_google_auth_url
    if not google_enabled():
        raise HTTPException(status_code=404, detail="Google OAuth not configured")

    redirect_uri = str(request.url_for("google_callback"))
    return {"url": get_google_auth_url(redirect_uri)}


@router.post("/api/v1/auth/google/callback", name="google_callback")
async def google_callback(request: Request):
    from app.oauth import google_enabled, exchange_google_code
    from app.users import get_user_by_provider, get_user_by_email, create_user, count_users
    from app.jwt_auth import create_access_token, create_refresh_token

    if not google_enabled():
        raise HTTPException(status_code=404, detail="Google OAuth not configured")

    body = await request.json()
    code = body.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    redirect_uri = body.get("redirect_uri", str(request.url_for("google_callback")))
    google_user = await exchange_google_code(code, redirect_uri)

    email = google_user.get("email", "").lower()
    sub = google_user.get("sub")
    if not email or not sub:
        raise HTTPException(status_code=400, detail="Could not retrieve email from Google")

    # Check if user exists by provider ID or email
    user = await get_user_by_provider("google", sub)
    if not user:
        user = await get_user_by_email(email)

    if not user:
        # New user registration via Google
        if settings.registration_mode == "admin":
            raise HTTPException(status_code=403, detail="Registration is disabled")

        user_count = await count_users()
        is_admin = user_count == 0

        user = await create_user(
            email=email,
            display_name=google_user.get("name", email.split("@")[0]),
            provider="google",
            provider_id=sub,
            is_admin=is_admin,
        )

    access = create_access_token(user["id"], user["email"], user["is_admin"])
    refresh = await create_refresh_token(user["id"])

    return AuthResponse(
        access_token=access,
        refresh_token=refresh,
        user=_safe_user(user),
    )


# ── Invite codes (admin-only) ───────────────────────────────────────────────

@router.post("/api/v1/auth/invites")
async def create_invite(req: InviteCreate, user: UserDep):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")

    from app.db import get_pool
    code = secrets.token_urlsafe(8)
    pool = get_pool()
    async with pool.acquire() as conn:
        from datetime import datetime, timedelta, timezone
        expires = None
        if req.expires_in_hours:
            expires = datetime.now(timezone.utc) + timedelta(hours=req.expires_in_hours)
        row = await conn.fetchrow(
            """
            INSERT INTO invite_codes (code, created_by, email, expires_at)
            VALUES ($1, $2, $3, $4)
            RETURNING id, code, email, expires_at, created_at
            """,
            code, UUID(user.id), req.email, expires,
        )
    return dict(row)


@router.get("/api/v1/auth/invites")
async def list_invites(user: UserDep):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")

    from app.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, code, email, used_by, used_at, expires_at, created_at "
            "FROM invite_codes WHERE used_by IS NULL AND (expires_at IS NULL OR expires_at > NOW()) "
            "ORDER BY created_at DESC"
        )
    return [dict(r) for r in rows]


@router.delete("/api/v1/auth/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: UUID, user: UserDep):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")

    from app.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM invite_codes WHERE id = $1 AND used_by IS NULL",
            invite_id,
        )
    if result != "DELETE 1":
        raise HTTPException(status_code=404, detail="Invite not found or already used")


# ── Admin user management ────────────────────────────────────────────────────

class AdminCreateUser(BaseModel):
    email: str
    display_name: str | None = None
    is_admin: bool = False

@router.post("/api/v1/admin/users")
async def admin_create_user(req: AdminCreateUser, user: UserDep):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")

    from app.users import create_user, get_user_by_email

    existing = await get_user_by_email(req.email.lower())
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    temp_password = secrets.token_urlsafe(12)
    password_hash = _hash_password(temp_password)

    new_user = await create_user(
        email=req.email.lower(),
        password_hash=password_hash,
        display_name=req.display_name or req.email.split("@")[0],
        is_admin=req.is_admin,
    )

    return {**_safe_user(new_user), "temporary_password": temp_password}


# ── Conversations ────────────────────────────────────────────────────────────

@router.get("/api/v1/conversations")
async def list_conversations_endpoint(
    user: UserDep,
    archived: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    from app.conversations import list_conversations
    return await list_conversations(user.id, limit=limit, offset=offset, include_archived=archived)


@router.post("/api/v1/conversations", status_code=201)
async def create_conversation_endpoint(req: ConversationCreate, user: UserDep):
    from app.conversations import create_conversation
    return await create_conversation(user.id, title=req.title)


@router.get("/api/v1/conversations/{conversation_id}")
async def get_conversation_endpoint(conversation_id: str, user: UserDep):
    from app.conversations import get_conversation
    conv = await get_conversation(conversation_id, user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.patch("/api/v1/conversations/{conversation_id}")
async def update_conversation_endpoint(
    conversation_id: str, req: ConversationUpdate, user: UserDep
):
    from app.conversations import update_conversation
    updates = {}
    if req.title is not None:
        updates["title"] = req.title
    if req.is_archived is not None:
        updates["is_archived"] = req.is_archived
    conv = await update_conversation(conversation_id, user.id, **updates)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/api/v1/conversations/{conversation_id}", status_code=204)
async def delete_conversation_endpoint(conversation_id: str, user: UserDep):
    from app.conversations import delete_conversation
    deleted = await delete_conversation(conversation_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/api/v1/conversations/{conversation_id}/messages")
async def get_messages_endpoint(
    conversation_id: str,
    user: UserDep,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    from app.conversations import get_messages
    return await get_messages(conversation_id, user.id, limit=limit, offset=offset)


@router.post("/api/v1/conversations/{conversation_id}/messages/import")
async def import_messages_endpoint(
    conversation_id: str, req: MessageImport, user: UserDep
):
    from app.conversations import import_messages
    count = await import_messages(conversation_id, user.id, req.messages)
    return {"imported": count}
