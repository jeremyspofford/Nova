"""
Orchestrator FastAPI router — agent lifecycle, task routing, key management, usage reporting.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
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
from app.auth import AdminDep, ApiKeyDep
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


async def _sse_stream(agent_id: str, stream_gen, error_label: str = "stream", sandbox_token=None):
    """SSE-formatted wrapper: yields deltas from run_agent_turn_streaming, handles errors, resets agent status."""
    try:
        async for delta in stream_gen:
            yield f"data: {delta}\n\n".encode()
        yield b"data: [DONE]\n\n"
    except Exception as e:
        log.error("%s error (agent=%s): %s", error_label, agent_id, e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()
        yield b"data: [DONE]\n\n"
    finally:
        await update_agent_status(agent_id, AgentStatus.idle)
        if sandbox_token is not None:
            reset_sandbox(sandbox_token)


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

    # Set sandbox tier from global config for interactive turns
    tier = SandboxTier(_settings.shell_sandbox) if _settings.shell_sandbox in SandboxTier.__members__ else SandboxTier.workspace
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

    # Set sandbox tier from global config for interactive turns
    tier = SandboxTier(_settings.shell_sandbox) if _settings.shell_sandbox in SandboxTier.__members__ else SandboxTier.workspace
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
    output_style: str | None = None
    custom_instructions: str | None = None
    web_search: bool = False
    deep_research: bool = False


@router.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest, _admin: AdminDep):
    """
    Streaming chat directly with the primary Nova agent. Admin-only.

    This endpoint is for the dashboard chat UI — it uses the admin secret
    so no API key is needed. External API consumers should use
    POST /v1/chat/completions with an API key instead.

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
    from app.model_resolver import resolve_default_model
    model = req.model or await resolve_default_model()
    explicit_model = bool(req.model)
    task_id = uuid4()
    session_id = req.session_id or str(uuid4())

    # Build style/research modifiers for system prompt
    system_prompt = agent.config.system_prompt
    modifiers: list[str] = []
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

    # Set sandbox tier from global config for interactive turns
    from app.config import settings as _settings
    tier = SandboxTier(_settings.shell_sandbox) if _settings.shell_sandbox in SandboxTier.__members__ else SandboxTier.workspace
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
            ),
            error_label="Chat stream",
            sandbox_token=sandbox_token,
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
        update_desc = req.description is not None
        if update_desc:
            row = await conn.fetchrow(
                """
                UPDATE platform_config
                SET value = $2::jsonb, description = $3, updated_at = NOW()
                WHERE key = $1
                RETURNING key, value, description, is_secret, updated_at
                """,
                key, req.value, req.description,
            )
        else:
            row = await conn.fetchrow(
                """
                UPDATE platform_config
                SET value = $2::jsonb, updated_at = NOW()
                WHERE key = $1
                RETURNING key, value, description, is_secret, updated_at
                """,
                key, req.value,
            )
    if not row:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    # Publish llm.* config changes to Redis db1 (llm-gateway's db) for runtime pickup
    if key.startswith("llm."):
        try:
            from app.config_sync import push_config_to_redis
            await push_config_to_redis(key, req.value)
        except Exception as e:
            log.warning("Failed to publish config %s to Redis: %s", key, e)

    return _config_row(dict(row))


# ── Tool catalog (admin-only) ─────────────────────────────────────────────────

@router.get("/api/v1/tools")
async def list_available_tools(_admin: AdminDep):
    """Return all available tools grouped by category. Admin-only."""
    from app.tools.code_tools import CODE_TOOLS
    from app.tools.git_tools import GIT_TOOLS
    from app.tools.platform_tools import PLATFORM_TOOLS
    from app.pipeline.tools.registry import get_tools_by_server

    def _to_list(defs):
        return [{"name": t.name, "description": t.description} for t in defs]

    categories = [
        {"category": "Code Tools", "source": "builtin", "tools": _to_list(CODE_TOOLS)},
        {"category": "Git Tools", "source": "builtin", "tools": _to_list(GIT_TOOLS)},
        {"category": "Platform Tools", "source": "builtin", "tools": _to_list(PLATFORM_TOOLS)},
    ]
    categories.extend(get_tools_by_server())
    return categories


# ── Usage reporting (admin-only) ──────────────────────────────────────────────

@router.get("/api/v1/usage")
async def get_usage(
    _admin: AdminDep,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Recent usage events with key name join, newest first. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, u.api_key_id, k.name AS key_name,
                   u.agent_id, u.session_id, u.model,
                   u.input_tokens, u.output_tokens, u.cost_usd,
                   u.duration_ms, u.created_at
            FROM   usage_events u
            LEFT   JOIN api_keys k ON k.id = u.api_key_id
            ORDER  BY u.created_at DESC
            LIMIT  $1 OFFSET $2
            """,
            limit, offset,
        )
    return [dict(r) for r in rows]
