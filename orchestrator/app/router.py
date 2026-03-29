"""
Orchestrator FastAPI router — agent lifecycle, task routing, key management, usage reporting.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from nova_contracts import (
    AgentInfo,
    AgentStatus,
    CreateAgentRequest,
    SubmitTaskRequest,
    TaskResult,
)

from app.agents.runner import run_agent_turn, run_agent_turn_streaming
from app.auth import AdminDep, ApiKeyDep, UserDep
from app.tools.sandbox import SandboxTier, set_sandbox, reset_sandbox
from app.db import (
    create_api_key_record,
    generate_api_key,
    get_pool,
    list_api_keys,
    revoke_api_key,
)
from app.store import (
    create_agent,
    delete_agent,
    get_agent,
    get_task_result,
    list_agents,
    store_task_result,
    update_agent_config,
    update_agent_status,
)

log = logging.getLogger(__name__)
router = APIRouter(tags=["orchestrator"])


async def _sse_stream(agent_id: str, stream_gen, error_label: str = "stream", sandbox_token=None,
                      conversation_id: str | None = None, user_message: str | None = None,
                      session_id: str | None = None, message_metadata: dict | None = None):
    """SSE-formatted wrapper: yields deltas from run_agent_turn_streaming, handles errors, resets agent status."""
    accumulated = ""
    model_used = None
    try:
        async for delta in stream_gen:
            # JSON events (status/meta) from the runner — pass through as-is
            if isinstance(delta, str) and delta.startswith("{"):
                try:
                    parsed = json.loads(delta)
                    if isinstance(parsed, dict) and "meta" in parsed:
                        model_used = parsed["meta"].get("model")
                    yield f"data: {delta}\n\n".encode()
                    continue
                except (json.JSONDecodeError, KeyError):
                    pass  # Not valid JSON — treat as text delta below
            # Text deltas: wrap in JSON so newlines can't break SSE framing
            accumulated += delta
            yield f"data: {json.dumps({'t': delta})}\n\n".encode()
        yield b"data: [DONE]\n\n"
    except Exception as e:
        log.error("%s error (agent=%s): %s", error_label, agent_id, e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()
        yield b"data: [DONE]\n\n"
    finally:
        await update_agent_status(agent_id, AgentStatus.idle)
        if sandbox_token is not None:
            reset_sandbox(sandbox_token)
        # Persist messages to conversation if conversation_id provided
        if conversation_id and accumulated:
            try:
                from app.conversations import add_message, generate_title
                if user_message:
                    await add_message(conversation_id, "user", user_message, metadata=message_metadata)
                await add_message(conversation_id, "assistant", accumulated, model_used=model_used)
                # Auto-title: check if conversation still has no title
                from app.db import get_pool
                pool = get_pool()
                async with pool.acquire() as conn:
                    title = await conn.fetchval(
                        "SELECT title FROM conversations WHERE id = $1",
                        UUID(conversation_id),
                    )
                if not title and user_message:
                    asyncio.create_task(generate_title(conversation_id, user_message))
            except Exception as e:
                log.warning("Failed to persist conversation messages: %s", e)
        # Release concurrent stream lock
        try:
            from app.store import get_redis
            _redis = get_redis()
            lock_key = f"nova:chat:streaming:{conversation_id or session_id}"
            await _redis.delete(lock_key)
        except Exception:
            pass  # Lock auto-expires via TTL if cleanup fails


# ── Sandbox tier (runtime from DB) ────────────────────────────────────────────

async def _get_sandbox_tier() -> SandboxTier:
    """Read the sandbox tier from platform_config (DB), falling back to env var."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value #>> '{}' AS val FROM platform_config WHERE key = 'shell.sandbox'"
            )
        if row and row["val"] in SandboxTier.__members__:
            return SandboxTier(row["val"])
    except Exception:
        pass
    from app.config import settings as _s
    return SandboxTier(_s.shell_sandbox) if _s.shell_sandbox in SandboxTier.__members__ else SandboxTier.workspace


# ── Agent lifecycle ───────────────────────────────────────────────────────────

@router.post("/api/v1/agents", response_model=AgentInfo, status_code=201)
async def create_new_agent(req: CreateAgentRequest, _key: ApiKeyDep):
    return await create_agent(req.config)


@router.get("/api/v1/agents", response_model=list[AgentInfo])
async def get_agents(_key: ApiKeyDep):
    return await list_agents()


@router.get("/api/v1/agents/{agent_id}", response_model=AgentInfo)
async def get_agent_info(agent_id: str, _key: ApiKeyDep):
    agent = await get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


class UpdateAgentConfigRequest(BaseModel):
    model: str | None = None
    system_prompt: str | None = None
    fallback_models: list[str] = []


@router.patch("/api/v1/agents/{agent_id}/config", response_model=AgentInfo)
async def patch_agent_config(
    agent_id: str, req: UpdateAgentConfigRequest, _admin: AdminDep
):
    """Update model, system prompt, and fallback model list for a Redis agent. Admin-only."""
    agent = await update_agent_config(
        agent_id,
        model=req.model,
        system_prompt=req.system_prompt,
        fallback_models=req.fallback_models,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/api/v1/agents/{agent_id}", status_code=204)
async def delete_agent_endpoint(agent_id: str, _key: ApiKeyDep):
    """Permanently delete an agent. Use ?soft=true to only mark it stopped."""
    existed = await delete_agent(agent_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Agent not found")


@router.delete("/api/v1/agents", status_code=200)
async def bulk_delete_agents(_admin: AdminDep, confirm: bool = Query(default=False)):
    """Delete all agents. Admin-only. Requires ?confirm=true to prevent accidents."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to delete all agents. This cannot be undone.",
        )
    agents = await list_agents()
    for agent in agents:
        await delete_agent(str(agent.id))
    return {"deleted": len(agents)}


# ── Task routing ──────────────────────────────────────────────────────────────

@router.post("/api/v1/tasks", response_model=TaskResult, status_code=202)
async def submit_task(req: SubmitTaskRequest, key: ApiKeyDep):
    from app.config import settings as _settings

    agent = await get_agent(str(req.agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status == AgentStatus.stopped:
        raise HTTPException(status_code=409, detail="Agent is stopped")

    task_id = uuid4()
    session_id = req.session_id or str(uuid4())
    await update_agent_status(str(req.agent_id), AgentStatus.running)

    # Set sandbox tier from DB config for this request
    tier = await _get_sandbox_tier()
    sandbox_token = set_sandbox(tier)
    try:
        result = await run_agent_turn(
            agent_id=str(req.agent_id),
            task_id=task_id,
            session_id=session_id,
            messages=req.messages,
            model=agent.config.model,
            system_prompt=agent.config.system_prompt,
            api_key_id=key.id,
            agent_name=agent.config.name,
        )
        await store_task_result(result)
        await update_agent_status(str(req.agent_id), AgentStatus.idle)
        return result
    finally:
        reset_sandbox(sandbox_token)


@router.post("/api/v1/tasks/stream")
async def submit_task_streaming(req: SubmitTaskRequest, key: ApiKeyDep):
    from app.config import settings as _settings

    agent = await get_agent(str(req.agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task_id = uuid4()
    session_id = req.session_id or str(uuid4())
    await update_agent_status(str(req.agent_id), AgentStatus.running)

    # Set sandbox tier from DB config for this request
    tier = await _get_sandbox_tier()
    sandbox_token = set_sandbox(tier)

    return StreamingResponse(
        _sse_stream(
            str(req.agent_id),
            run_agent_turn_streaming(
                agent_id=str(req.agent_id),
                task_id=task_id,
                session_id=session_id,
                messages=req.messages,
                model=agent.config.model,
                system_prompt=agent.config.system_prompt,
                api_key_id=key.id,
                skip_tool_preresolution=True,
                agent_name=agent.config.name,
            ),
            error_label="Streaming",
            sandbox_token=sandbox_token,
        ),
        media_type="text/event-stream",
    )


@router.get("/api/v1/tasks/{task_id}", response_model=TaskResult)
async def get_task(task_id: str, _key: ApiKeyDep):
    result = await get_task_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


# ── Direct chat (admin dashboard) ────────────────────────────────────────────

BASE_FORMAT_PROMPT = (
    "IMPORTANT — Response formatting rules:\n"
    "- Always use markdown. Start sections with ## headings.\n"
    "- Use bullet points for lists, bold for key terms.\n"
    "- Keep paragraphs to 2-3 sentences max, separated by blank lines.\n"
    "- Never write walls of text. Break every response into clear sections.\n"
    "- Example structure:\n"
    "  ## Overview\n"
    "  Brief summary here.\n\n"
    "  ## Details\n"
    "  - Point one\n"
    "  - Point two"
)

STYLE_PROMPTS = {
    "concise": "Be concise and brief. Give short, direct answers without unnecessary elaboration.",
    "detailed": "Give thorough, detailed answers with examples and explanations.",
    "technical": "Use precise technical language. Include code examples, specifications, and implementation details where relevant.",
    "creative": "Be creative and expressive. Use metaphors, analogies, and engaging language.",
    "eli5": "Explain like I'm 5. Use simple words, analogies, and avoid jargon.",
}


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    output_style: str | None = None
    custom_instructions: str | None = None
    web_search: bool = False
    deep_research: bool = False
    metadata: dict | None = None  # channel tagging from bridge


# ── Chat pod config cache ─────────────────────────────────────────────────────
# Pod config is loaded from DB on first chat request, then cached with a short
# TTL to avoid per-message queries. Config changes take effect within the TTL.

_chat_pod_cache: dict | None = None
_chat_pod_cache_at: float = 0.0
_CHAT_POD_TTL = 8.0  # seconds


async def _get_chat_pod_config() -> dict | None:
    """Load the chat pod and its first agent config. Returns None if no chat pod."""
    global _chat_pod_cache, _chat_pod_cache_at
    now = _time.monotonic()
    if _chat_pod_cache is not None and (now - _chat_pod_cache_at) < _CHAT_POD_TTL:
        return _chat_pod_cache

    from app.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id AS pod_id, p.name AS pod_name,
                   pa.model, pa.system_prompt, pa.allowed_tools,
                   pa.temperature, pa.max_tokens
            FROM pods p
            JOIN pod_agents pa ON pa.pod_id = p.id
            WHERE p.is_chat_default = true AND p.enabled = true
            ORDER BY pa.position ASC
            LIMIT 1
            """
        )
    if row:
        _chat_pod_cache = dict(row)
    else:
        _chat_pod_cache = None
    _chat_pod_cache_at = now
    return _chat_pod_cache


@router.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest, user: UserDep):
    """
    Streaming chat directly with the primary Nova agent. Admin-only.

    This endpoint is for the dashboard chat UI — it uses the admin secret
    so no API key is needed. External API consumers should use
    POST /v1/chat/completions with an API key instead.

    Chat is backed by the "chat pod" — a pod marked is_chat_default=true in
    the pods table. The pod's agent config controls model, system_prompt, and
    allowed tools. Falls back to legacy behavior if no chat pod is configured.

    - model: override the agent's configured model for this turn only
    - session_id: pass back the X-Session-Id header value to continue a conversation
    """
    agents = await list_agents()
    if not agents:
        raise HTTPException(
            status_code=503,
            detail="No agents available — Nova is still starting up",
        )

    # Use the primary agent (Nova) — first in the list by creation time
    agent = agents[0]
    is_guest = user.role == "guest"

    # Load chat pod config (cached, ~8s TTL)
    chat_pod = await _get_chat_pod_config()
    allowed_tools: list[str] | None = None
    if chat_pod and chat_pod.get("allowed_tools"):
        allowed_tools = list(chat_pod["allowed_tools"])

    # Guest isolation: validate model against allowlist
    if is_guest:
        from app.guest import validate_guest_model
        try:
            model = await validate_guest_model(req.model)
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))
        explicit_model = True  # prevent intelligent routing from overriding
    else:
        from app.model_resolver import resolve_default_model, is_auto_resolved
        # Pod model takes precedence over global default, request model overrides both
        pod_model = chat_pod["model"] if chat_pod and chat_pod.get("model") else None
        model = req.model or pod_model or await resolve_default_model()
        # Treat as explicit if user sent a model, pod has a model, or admin configured a specific default
        explicit_model = bool(req.model) or bool(pod_model) or not await is_auto_resolved()
    task_id = uuid4()
    # Use conversation_id as session_id when available (for memory-service compatibility)
    session_id = req.conversation_id or req.session_id or str(uuid4())

    # If conversation_id provided, verify ownership
    conversation_id = req.conversation_id
    if conversation_id:
        from app.conversations import get_conversation
        conv = await get_conversation(conversation_id, user.id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Concurrent stream lock — one stream per conversation at a time
    from app.store import get_redis
    lock_key = f"nova:chat:streaming:{conversation_id or session_id}"
    _redis = get_redis()
    if await _redis.exists(lock_key):
        raise HTTPException(
            status_code=409,
            detail="Nova is currently responding. Try again in a moment."
        )
    await _redis.set(lock_key, "1", ex=120)

    # Extract last user message for persistence
    user_message = None
    if conversation_id and req.messages:
        last_user = [m for m in req.messages if m.get("role") == "user"]
        if last_user:
            content = last_user[-1].get("content", "")
            user_message = content if isinstance(content, str) else str(content)

    # Guest isolation: use stripped-down system prompt with no context injection
    if is_guest:
        from app.guest import GUEST_SYSTEM_PROMPT
        system_prompt = GUEST_SYSTEM_PROMPT
    else:
        # Pod system prompt takes precedence over agent config default
        base_prompt = (chat_pod["system_prompt"] if chat_pod and chat_pod.get("system_prompt") else None) or agent.config.system_prompt
        # Build style/research modifiers for system prompt
        system_prompt = base_prompt
        modifiers: list[str] = [BASE_FORMAT_PROMPT]
        if req.output_style and req.output_style in STYLE_PROMPTS:
            modifiers.append(STYLE_PROMPTS[req.output_style])
        if req.custom_instructions:
            modifiers.append(req.custom_instructions.strip())
        if req.web_search:
            modifiers.append("You have web search available. Use it when the question benefits from current information.")
        if req.deep_research:
            modifiers.append("Perform thorough multi-step research. Search multiple queries, cross-reference sources, synthesize findings, and cite sources.")
        if modifiers:
            system_prompt = (system_prompt or "") + "\n\n" + "\n\n".join(modifiers)

    await update_agent_status(str(agent.id), AgentStatus.running)

    # Set sandbox tier from DB config for this request
    tier = await _get_sandbox_tier()
    sandbox_token = set_sandbox(tier)

    return StreamingResponse(
        _sse_stream(
            str(agent.id),
            run_agent_turn_streaming(
                agent_id=str(agent.id),
                task_id=task_id,
                session_id=session_id,
                messages=req.messages,
                model=model,
                system_prompt=system_prompt,
                api_key_id=None,
                skip_tool_preresolution=True,
                explicit_model=explicit_model,
                guest_mode=is_guest,
                allowed_tools=allowed_tools,
                agent_name=agent.config.name,
            ),
            error_label="Chat stream",
            sandbox_token=sandbox_token,
            conversation_id=conversation_id,
            user_message=user_message,
            session_id=session_id,
            message_metadata=req.metadata,
        ),
        media_type="text/event-stream",
        headers={
            "X-Session-Id": session_id,
            "Cache-Control": "no-cache",
        },
    )


# ── Key management (admin-only) ───────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str
    rate_limit_rpm: int = 60
    metadata: dict = {}


class KeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    is_active: bool
    rate_limit_rpm: int
    created_at: datetime
    last_used_at: datetime | None = None
    metadata: dict = {}


class CreateKeyResponse(KeyResponse):
    raw_key: str  # Returned ONCE at creation — never stored, never retrievable again


@router.post("/api/v1/keys", response_model=CreateKeyResponse, status_code=201)
async def create_key(req: CreateKeyRequest, _admin: AdminDep):
    """Create a new API key. Save raw_key immediately — it will not be shown again."""
    raw_key, key_hash, key_prefix = generate_api_key()
    row = await create_api_key_record(
        name=req.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        rate_limit_rpm=req.rate_limit_rpm,
        metadata=req.metadata,
    )
    return CreateKeyResponse(**row, raw_key=raw_key)


@router.get("/api/v1/keys", response_model=list[KeyResponse])
async def list_keys(_admin: AdminDep):
    """List all API keys. Raw keys are never returned — prefix and metadata only."""
    rows = await list_api_keys()
    return [KeyResponse(**r) for r in rows]


@router.delete("/api/v1/keys/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, _admin: AdminDep):
    """Deactivate an API key. Row is preserved in the DB for audit trail."""
    existed = await revoke_api_key(key_id)
    if not existed:
        raise HTTPException(status_code=404, detail="Key not found or already revoked")


@router.get("/api/v1/keys/validate")
async def validate_key(key: ApiKeyDep):
    """Validate an API key. Returns 200 if valid, 401 if not.

    Used internally by chat-api to authenticate WebSocket connections.
    """
    return {"valid": True, "name": key.name}


def _unwrap_jsonb_str(val: str | None) -> str:
    """Strip one layer of JSON string quoting if present.

    platform_config stores JSONB.  The dashboard sends values pre-encoded
    (e.g. '"Nova"') which becomes a JSONB *string*.  Extracting with
    ``#>> '{}'`` gives the text content, but values that were double-encoded
    arrive here with literal surrounding quotes — strip them.
    """
    if val and len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        try:
            return json.loads(val)
        except Exception:
            pass
    return val or ""


# ── Identity (public) ─────────────────────────────────────────────────────────

@router.get("/api/v1/identity")
async def get_identity() -> dict:
    """Public endpoint returning the AI's display name and greeting.
    No auth required - used by the dashboard UI."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value #>> '{}' AS val FROM platform_config "
            "WHERE key IN ('nova.name', 'nova.greeting')"
        )
    config = {r["key"]: _unwrap_jsonb_str(r["val"]) for r in rows}
    name = config.get("nova.name") or "Nova"
    greeting_template = config.get("nova.greeting") or ""
    greeting = greeting_template.replace("{name}", name) if greeting_template else ""
    return {"name": name, "greeting": greeting}


# ── Platform configuration (admin-only) ──────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    value: str              # JSON-encoded value (Python side handles parsing)
    description: str | None = None


def _config_row(row: dict) -> dict:
    """Decode JSONB value back to a Python scalar for the API response."""
    d = dict(row)
    d["updated_at"] = d["updated_at"].isoformat() if d.get("updated_at") else None
    # Decode the JSONB value so the frontend receives a plain string/number/null
    raw = d.get("value")
    try:
        d["value"] = json.loads(raw) if raw is not None else None
    except Exception:
        d["value"] = raw
    return d


@router.get("/api/v1/config")
async def list_platform_config(_admin: AdminDep) -> list[dict]:
    """Return all platform config entries. Values are decoded from JSONB. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value, description, is_secret, updated_at "
            "FROM platform_config ORDER BY key"
        )
    return [_config_row(dict(r)) for r in rows]


@router.get("/api/v1/config/{key}")
async def get_platform_config(key: str, _admin: AdminDep) -> dict:
    """Return a single platform config entry by key. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT key, value, description, is_secret, updated_at "
            "FROM platform_config WHERE key = $1", key
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return _config_row(dict(row))


@router.patch("/api/v1/config/{key}")
async def update_platform_config(
    key: str, req: ConfigUpdateRequest, _admin: AdminDep
) -> dict:
    """
    Update a single platform config entry. Admin-only.

    req.value must be a JSON-encoded string, e.g.:
      '"My persona text"'  →  stores the string  My persona text
      'null'               →  clears the value
      '42'                 →  stores the integer 42
    """
    # Validate that req.value is valid JSON before storing
    try:
        json.loads(req.value)
    except json.JSONDecodeError:
        # Treat as a bare string if it's not valid JSON — wrap it
        req.value = json.dumps(req.value)

    pool = get_pool()
    async with pool.acquire() as conn:
        desc = req.description or ''
        row = await conn.fetchrow(
            """
            INSERT INTO platform_config (key, value, description, updated_at)
            VALUES ($1, $2::jsonb, $3, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                description = CASE WHEN $3 = '' THEN platform_config.description ELSE EXCLUDED.description END,
                updated_at = NOW()
            RETURNING key, value, description, is_secret, updated_at
            """,
            key, req.value, desc,
        )

    # Publish llm.* config changes to Redis db1 (llm-gateway's db) for runtime pickup
    if key.startswith("llm."):
        try:
            from app.config_sync import push_config_to_redis
            await push_config_to_redis(key, req.value)
        except Exception as e:
            log.warning("Failed to publish config %s to Redis: %s", key, e)

    # Publish inference.* config changes to Redis for gateway pickup
    if key.startswith("inference."):
        try:
            from app.config_sync import push_config_to_redis
            await push_config_to_redis(key, req.value)
        except Exception as e:
            log.warning("Failed to publish config %s to Redis: %s", key, e)

    # Publish engram.* config changes to Redis for memory-service pickup
    if key.startswith("engram."):
        try:
            from app.config_sync import push_config_to_redis
            await push_config_to_redis(key, req.value)
        except Exception as e:
            log.warning("Failed to publish config %s to Redis: %s", key, e)

    # Publish voice.* config changes to Redis for voice-service pickup
    if key.startswith("voice."):
        try:
            from app.config_sync import push_config_to_redis
            await push_config_to_redis(key, req.value)
        except Exception as e:
            log.warning("Failed to publish config %s to Redis: %s", key, e)

    # Emit activity event for config changes
    try:
        from app.activity import emit_activity
        pool = get_pool()
        await emit_activity(
            pool, "config_updated", "orchestrator",
            f"Config '{key}' updated",
            metadata={"key": key},
        )
    except Exception:
        pass

    return _config_row(dict(row))


# ── Tool catalog (admin-only) ─────────────────────────────────────────────────

@router.get("/api/v1/tools")
async def list_available_tools(_admin: AdminDep):
    """Return all available tools grouped by category. Admin-only."""
    from app.tools.code_tools import CODE_TOOLS
    from app.tools.git_tools import GIT_TOOLS
    from app.tools.platform_tools import PLATFORM_TOOLS
    from app.tools.web_tools import WEB_TOOLS
    from app.tools.diagnosis_tools import DIAGNOSIS_TOOLS
    from app.tools.memory_tools import MEMORY_TOOLS
    from app.tools.introspect_tools import INTROSPECT_TOOLS
    from app.tools.intel_tools import INTEL_TOOLS
    from app.pipeline.tools.registry import get_tools_by_server

    def _to_list(defs):
        return [{"name": t.name, "description": t.description} for t in defs]

    categories = [
        {"category": "Code Tools", "source": "builtin", "tools": _to_list(CODE_TOOLS)},
        {"category": "Git Tools", "source": "builtin", "tools": _to_list(GIT_TOOLS)},
        {"category": "Platform Tools", "source": "builtin", "tools": _to_list(PLATFORM_TOOLS)},
        {"category": "Web Tools", "source": "builtin", "tools": _to_list(WEB_TOOLS)},
        {"category": "Diagnosis Tools", "source": "builtin", "tools": _to_list(DIAGNOSIS_TOOLS)},
        {"category": "Memory Tools", "source": "builtin", "tools": _to_list(MEMORY_TOOLS)},
        {"category": "Introspection Tools", "source": "builtin", "tools": _to_list(INTROSPECT_TOOLS)},
        {"category": "Intel Tools", "source": "builtin", "tools": _to_list(INTEL_TOOLS)},
    ]
    categories.extend(get_tools_by_server())
    return categories


# ── Tool permissions ──────────────────────────────────────────────────────────


class ToolPermissionUpdate(BaseModel):
    groups: dict[str, bool]  # {"Web": false, "Git": true}


@router.get("/api/v1/tool-permissions")
async def get_tool_permissions(_admin: AdminDep):
    """Return all tool groups with their enabled/disabled status."""
    from app.tool_permissions import get_tool_groups_with_status
    return await get_tool_groups_with_status()


@router.patch("/api/v1/tool-permissions")
async def update_tool_permissions(req: ToolPermissionUpdate, _admin: AdminDep):
    """Toggle tool groups on/off. Accepts {"groups": {"Web": false, "Git": true}}."""
    from app.tool_permissions import (
        get_disabled_tool_groups, get_valid_group_names,
        get_tool_groups_with_status, set_disabled_groups,
    )

    # Validate group names against registry
    valid = get_valid_group_names()
    unknown = set(req.groups.keys()) - valid
    if unknown:
        raise HTTPException(422, f"Unknown tool groups: {sorted(unknown)}")

    old_disabled = await get_disabled_tool_groups()
    new_disabled = set(old_disabled)
    for group, enabled in req.groups.items():
        if enabled:
            new_disabled.discard(group)
        else:
            new_disabled.add(group)
    await set_disabled_groups(new_disabled)

    # Audit log — record what changed
    if old_disabled != new_disabled:
        try:
            import json as _json
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO platform_config_audit
                        (config_key, old_value, new_value)
                    VALUES ($1, $2::jsonb, $3::jsonb)
                    """,
                    "tool_permissions",
                    _json.dumps({"disabled_groups": sorted(old_disabled)}),
                    _json.dumps({"disabled_groups": sorted(new_disabled)}),
                )
        except Exception as e:
            log.warning(f"Audit log write failed (non-critical): {e}")

    return await get_tool_groups_with_status()


# ── Usage reporting (admin-only) ──────────────────────────────────────────────

@router.get("/api/v1/training-data/export")
async def export_training_data(
    _admin: AdminDep,
    role: str | None = Query(default=None, description="Filter by pipeline role"),
    success_only: bool = Query(default=False, description="Only include successful pipelines"),
    format: str = Query(default="jsonl", description="Export format (jsonl)"),
):
    """Export pipeline training data as JSONL for fine-tuning. Admin-only."""
    import json as _json
    pool = get_pool()
    conditions = []
    params = []
    idx = 1

    if role:
        conditions.append(f"role = ${idx}")
        params.append(role)
        idx += 1
    if success_only:
        conditions.append(f"pipeline_success = ${idx}")
        params.append(True)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async def _stream():
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT prompt, response, model, role, input_tokens, output_tokens, "
                f"cost_usd, complexity, pipeline_success, stage_verdict, was_fallback, "
                f"temperature, created_at "
                f"FROM pipeline_training_logs {where} "
                f"ORDER BY created_at ASC",
                *params,
            )
            for row in rows:
                entry = {
                    "messages": row["prompt"],
                    "response": row["response"],
                    "model": row["model"],
                    "role": row["role"],
                    "input_tokens": row["input_tokens"],
                    "output_tokens": row["output_tokens"],
                    "cost_usd": float(row["cost_usd"]) if row["cost_usd"] else None,
                    "complexity": row["complexity"],
                    "pipeline_success": row["pipeline_success"],
                    "stage_verdict": row["stage_verdict"],
                    "was_fallback": row["was_fallback"],
                }
                yield _json.dumps(entry, default=str) + "\n"

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=training-data.jsonl"},
    )


@router.get("/api/v1/training-data/count")
async def training_data_count(
    _admin: AdminDep,
    role: str | None = Query(default=None),
):
    """Count training data entries. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if role:
            row = await conn.fetchrow(
                "SELECT count(*) AS cnt FROM pipeline_training_logs WHERE role = $1", role
            )
        else:
            row = await conn.fetchrow("SELECT count(*) AS cnt FROM pipeline_training_logs")
    return {"count": row["cnt"]}


@router.get("/api/v1/usage")
async def get_usage(
    _admin: AdminDep,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    include_outcomes: bool = Query(default=False),
):
    """Recent usage events with key name join, newest first. Admin-only.

    By default, excludes zero-token outcome events (e.g. cortex scoring).
    Pass include_outcomes=true to include them.
    """
    pool = get_pool()
    outcome_filter = "" if include_outcomes else "WHERE (u.input_tokens > 0 OR u.output_tokens > 0)"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT u.id, u.api_key_id, k.name AS key_name,
                   u.agent_id, u.session_id, u.model,
                   u.input_tokens, u.output_tokens, u.cost_usd,
                   u.duration_ms, u.created_at,
                   u.agent_name, u.pod_name
            FROM   usage_events u
            LEFT   JOIN api_keys k ON k.id = u.api_key_id
            {outcome_filter}
            ORDER  BY u.created_at DESC
            LIMIT  $1 OFFSET $2
            """,
            limit, offset,
        )
    return [dict(r) for r in rows]


class UsageEventRequest(BaseModel):
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    duration_ms: int | None = None
    outcome_score: float | None = None
    outcome_confidence: float | None = None
    metadata: dict | None = None
    agent_name: str | None = None
    pod_name: str | None = None


@router.post("/api/v1/usage/events", status_code=201)
async def create_usage_event(req: UsageEventRequest, _key: ApiKeyDep):
    """Accept usage events from external services (e.g. cortex)."""
    from app.db import insert_usage_event
    await insert_usage_event(
        api_key_id=None,
        agent_id=None,
        session_id=None,
        model=req.model,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        cost_usd=req.cost_usd,
        duration_ms=req.duration_ms,
        metadata=req.metadata,
        outcome_score=req.outcome_score,
        outcome_confidence=req.outcome_confidence,
        agent_name=req.agent_name,
        pod_name=req.pod_name,
    )
    return {"status": "created"}


# ── Usage summary (dashboard overview) ────────────────────────────────────────

@router.get("/api/v1/usage/summary")
async def usage_summary(
    _admin: AdminDep,
    period: str = Query(default="week", regex="^(day|week|month|year)$"),
) -> dict:
    """Aggregated usage summary for a given period. Admin-only."""
    period_days = {"day": 1, "week": 7, "month": 30, "year": 365}
    days = period_days.get(period, 7)
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    pool = get_pool()
    async with pool.acquire() as conn:
        # Current period totals
        totals = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(cost_usd), 0)::float AS total_cost_usd,
                   COUNT(*) AS total_requests
            FROM usage_events
            WHERE created_at >= $1
            """,
            current_start,
        )
        # Previous period totals (for comparison)
        prev_totals = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(cost_usd), 0)::float AS total_cost_usd
            FROM usage_events
            WHERE created_at >= $1 AND created_at < $2
            """,
            previous_start, current_start,
        )
        # By model
        by_model_rows = await conn.fetch(
            """
            SELECT model,
                   COALESCE(SUM(cost_usd), 0)::float AS cost_usd,
                   COUNT(*) AS requests
            FROM usage_events
            WHERE created_at >= $1
            GROUP BY model
            ORDER BY requests DESC
            """,
            current_start,
        )
        # By day
        by_day_rows = await conn.fetch(
            """
            SELECT DATE(created_at) AS date,
                   COALESCE(SUM(cost_usd), 0)::float AS cost_usd,
                   COUNT(*) AS requests
            FROM usage_events
            WHERE created_at >= $1
            GROUP BY DATE(created_at)
            ORDER BY date
            """,
            current_start,
        )

    prev_cost = float(prev_totals["total_cost_usd"]) if prev_totals else 0
    current_cost = float(totals["total_cost_usd"])
    vs_previous_pct = (
        round(((current_cost - prev_cost) / prev_cost) * 100, 1)
        if prev_cost > 0 else 0.0
    )

    return {
        "total_cost_usd": current_cost,
        "total_requests": totals["total_requests"],
        "by_model": [
            {"model": r["model"], "cost_usd": r["cost_usd"], "requests": r["requests"]}
            for r in by_model_rows
        ],
        "by_day": [
            {"date": r["date"].isoformat(), "cost_usd": r["cost_usd"], "requests": r["requests"]}
            for r in by_day_rows
        ],
        "vs_previous_period_pct": vs_previous_pct,
    }


# ── Health overview (dashboard) ───────────────────────────────────────────────

@router.get("/api/v1/health/overview")
async def health_overview(_admin: AdminDep) -> dict:
    """Ping all services and report latency. Admin-only."""
    import httpx

    services_to_check = [
        ("llm-gateway", "http://llm-gateway:8001/health/ready"),
        ("memory-service", "http://memory-service:8002/health/ready"),
        ("cortex", "http://cortex:8100/health/ready"),
        ("recovery", "http://recovery:8888/health/ready"),
    ]

    results = []

    # Orchestrator is self — always up if this endpoint is responding
    results.append({"name": "orchestrator", "status": "healthy", "latency_ms": 0})

    # HTTP service checks
    async def _check_http(name: str, url: str) -> dict:
        start = _time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                latency = int((_time.monotonic() - start) * 1000)
                status = "healthy" if resp.status_code == 200 else "degraded"
                return {"name": name, "status": status, "latency_ms": latency}
        except Exception:
            latency = int((_time.monotonic() - start) * 1000)
            return {"name": name, "status": "down", "latency_ms": latency}

    http_tasks = [_check_http(name, url) for name, url in services_to_check]
    http_results = await asyncio.gather(*http_tasks)
    results.extend(http_results)

    # Postgres check
    start = _time.monotonic()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        latency = int((_time.monotonic() - start) * 1000)
        results.append({"name": "postgres", "status": "healthy", "latency_ms": latency})
    except Exception:
        latency = int((_time.monotonic() - start) * 1000)
        results.append({"name": "postgres", "status": "down", "latency_ms": latency})

    # Redis check
    start = _time.monotonic()
    try:
        from app.store import get_redis as get_app_redis
        redis = get_app_redis()
        await redis.ping()
        latency = int((_time.monotonic() - start) * 1000)
        results.append({"name": "redis", "status": "healthy", "latency_ms": latency})
    except Exception:
        latency = int((_time.monotonic() - start) * 1000)
        results.append({"name": "redis", "status": "down", "latency_ms": latency})

    # Compute aggregate
    latencies = [r["latency_ms"] for r in results if r["latency_ms"] > 0]
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
    statuses = {r["status"] for r in results}
    if "down" in statuses:
        overall = "degraded"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "services": results,
        "avg_latency_ms": avg_latency,
        "overall_status": overall,
    }


# ── Activity feed ──────────────────────────────────────────────────────────────

@router.get("/api/v1/activity")
async def activity_feed(
    _admin: AdminDep,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """Recent activity events for the dashboard feed. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, service, severity, summary, metadata, created_at
            FROM activity_events
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
    result = []
    for r in rows:
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat()
        # metadata is stored as JSONB text — parse it
        meta = d.get("metadata")
        if isinstance(meta, str):
            try:
                d["metadata"] = json.loads(meta)
            except Exception:
                d["metadata"] = {}
        result.append(d)
    return result


# ── Model routing stats ───────────────────────────────────────────────────────

@router.get("/api/v1/models/routing-stats")
async def model_routing_stats(
    _admin: AdminDep,
    period: str = Query(default="7d"),
) -> dict:
    """Per-model usage aggregation for routing analytics. Admin-only."""
    # Parse period string (e.g. "7d", "30d", "1d")
    try:
        days = int(period.rstrip("d"))
    except (ValueError, AttributeError):
        days = 7

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT model,
              COUNT(*) AS requests,
              COALESCE(AVG(input_tokens + output_tokens), 0)::int AS avg_tokens,
              COALESCE(AVG(duration_ms), 0)::int AS avg_latency_ms,
              COALESCE(SUM(cost_usd), 0)::float AS cost_usd
            FROM usage_events
            WHERE created_at >= $1
            GROUP BY model
            ORDER BY requests DESC
            """,
            cutoff,
        )
        # Fallback rate: count events where metadata has 'was_fallback' = true
        fallback_row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE metadata->>'was_fallback' = 'true') AS fallback_count,
              COUNT(*) AS total
            FROM usage_events
            WHERE created_at >= $1
            """,
            cutoff,
        )
        # Category distribution from metadata
        cat_rows = await conn.fetch(
            """
            SELECT metadata->>'category' AS category, COUNT(*) AS cnt
            FROM usage_events
            WHERE created_at >= $1
              AND metadata->>'category' IS NOT NULL
            GROUP BY metadata->>'category'
            """,
            cutoff,
        )

    total = fallback_row["total"] if fallback_row else 0
    fallback_count = fallback_row["fallback_count"] if fallback_row else 0
    fallback_rate = round((fallback_count / total) * 100, 1) if total > 0 else 0.0

    return {
        "by_model": [
            {
                "model": r["model"],
                "requests": r["requests"],
                "avg_tokens": r["avg_tokens"],
                "avg_latency_ms": r["avg_latency_ms"],
                "cost_usd": r["cost_usd"],
            }
            for r in rows
        ],
        "fallback_rate_pct": fallback_rate,
        "category_distribution": {r["category"]: r["cnt"] for r in cat_rows},
    }
