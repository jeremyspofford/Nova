"""
Pipeline API router — async task submission, status polling, pod + agent management.

Endpoints:
  POST   /api/v1/pipeline/tasks                  Submit a task to the async queue
  GET    /api/v1/pipeline/tasks                  List recent tasks (with filters)
  GET    /api/v1/pipeline/tasks/{task_id}        Get task status + output
  POST   /api/v1/pipeline/tasks/{task_id}/cancel Cancel a queued/pending task

  GET    /api/v1/pods                            List all pods
  POST   /api/v1/pods                            Create a new pod (admin)
  GET    /api/v1/pods/{pod_id}                   Get pod details + agents
  PATCH  /api/v1/pods/{pod_id}                   Update pod settings (admin)
  DELETE /api/v1/pods/{pod_id}                   Delete pod and its agents (admin)

  GET    /api/v1/pods/{pod_id}/agents            List agents in a pod
  POST   /api/v1/pods/{pod_id}/agents            Add agent to pod (admin)
  PATCH  /api/v1/pods/{pod_id}/agents/{agent_id} Update agent config (admin)
  DELETE /api/v1/pods/{pod_id}/agents/{agent_id} Remove agent from pod (admin)

  GET    /api/v1/pipeline/dead-letter            Inspect dead-letter queue (admin)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.auth import AdminDep, ApiKeyDep
from app.config import settings
from app.db import get_pool
from app.queue import dead_letter_depth, enqueue_task, queue_depth

log = logging.getLogger(__name__)
router = APIRouter(tags=["pipeline"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class SubmitPipelineTaskRequest(BaseModel):
    user_input: str
    pod_name: str | None = None     # None → settings.default_pod_name
    metadata: dict[str, Any] = {}


class PipelineTaskResponse(BaseModel):
    task_id: str
    status: str
    pod_id: str | None
    queued_at: datetime | None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_stage: str | None = None
    output: str | None = None
    error: str | None = None
    retry_count: int
    metadata: dict[str, Any]


class PodRequest(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    routing_keywords: list[str] = []
    default_model: str | None = None
    max_cost_usd: float | None = None
    max_execution_seconds: int = 300
    require_human_review: str = "on_escalation"   # always | never | on_escalation
    escalation_threshold: str = "high"            # low | medium | high | critical
    metadata: dict[str, Any] = {}


class PodResponse(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    routing_keywords: list[str]
    default_model: str | None
    max_cost_usd: float | None
    max_execution_seconds: int
    require_human_review: str
    escalation_threshold: str
    metadata: dict[str, Any]
    created_at: datetime


class AgentRequest(BaseModel):
    name: str
    role: str                          # context | task | guardrail | code_review | decision
    enabled: bool = True
    position: int = 0                  # lower = runs first
    model: str | None = None           # None → pod default → service default
    fallback_models: list[str] = []    # tried in order when primary model fails
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout_seconds: int = 120
    max_retries: int = 2
    system_prompt: str | None = None
    allowed_tools: list[str] | None = None   # None → all tools
    on_failure: str = "abort"          # abort | skip | escalate
    run_condition: dict[str, Any] = {"type": "always"}
    artifact_type: str | None = None
    parallel_group: str | None = None


class AgentResponse(AgentRequest):
    id: str
    pod_id: str
    created_at: datetime


# ── Pipeline task endpoints ────────────────────────────────────────────────────

@router.post("/api/v1/pipeline/tasks", status_code=202)
async def submit_pipeline_task(
    req: SubmitPipelineTaskRequest,
    key: ApiKeyDep,
) -> dict:
    """
    Submit a task to the async pipeline queue.
    Returns immediately with task_id — use GET /api/v1/pipeline/tasks/{task_id} to poll.
    """
    pod_name = req.pod_name or settings.default_pod_name
    pool = get_pool()

    async with pool.acquire() as conn:
        # Resolve pod_id from name (optional — executor falls back to default if NULL)
        pod_row = await conn.fetchrow(
            "SELECT id FROM pods WHERE name = $1 AND enabled = true", pod_name
        )
        pod_id = str(pod_row["id"]) if pod_row else None

        # Create task row
        task_row = await conn.fetchrow(
            """
            INSERT INTO tasks
                (user_input, pod_id, status, metadata,
                 retry_count, max_retries, queued_at, checkpoint)
            VALUES
                ($1, $2::uuid, 'queued', $3::jsonb,
                 0, $4, now(), '{}')
            RETURNING id, queued_at
            """,
            req.user_input,
            pod_id,
            {**req.metadata, "api_key_id": str(key.id) if key.id else None},  # dict → codec handles JSONB
            settings.task_default_max_retries,
        )

    task_id = str(task_row["id"])
    await enqueue_task(task_id)

    log.info("Task %s submitted (pod=%s)", task_id, pod_name)
    return {
        "task_id": task_id,
        "status": "queued",
        "pod_name": pod_name,
        "queued_at": task_row["queued_at"].isoformat(),
    }


@router.get("/api/v1/pipeline/tasks")
async def list_pipeline_tasks(
    _key: ApiKeyDep,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    pod_id: str | None = Query(default=None),
) -> list[dict]:
    """List recent pipeline tasks, newest first. Optionally filter by status or pod."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.status, t.pod_id, p.name AS pod_name,
                   t.user_input, t.output, t.error, t.current_stage,
                   t.retry_count, t.max_retries,
                   t.queued_at, t.started_at, t.completed_at, t.metadata
            FROM tasks t
            LEFT JOIN pods p ON p.id = t.pod_id
            WHERE ($1::text IS NULL OR t.status = $1)
              AND ($2::uuid IS NULL OR t.pod_id = $2::uuid)
            ORDER BY t.queued_at DESC
            LIMIT $3 OFFSET $4
            """,
            status, pod_id, limit, offset,
        )
    return [_task_dict(r) for r in rows]


@router.get("/api/v1/pipeline/tasks/{task_id}")
async def get_pipeline_task(task_id: str, _key: ApiKeyDep) -> dict:
    """Get the full status and output of a pipeline task."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.status, t.pod_id, p.name AS pod_name,
                   t.user_input, t.output, t.error, t.current_stage,
                   t.retry_count, t.max_retries,
                   t.queued_at, t.started_at, t.completed_at, t.metadata
            FROM tasks t
            LEFT JOIN pods p ON p.id = t.pod_id
            WHERE t.id = $1::uuid
            """,
            task_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(row)


@router.post("/api/v1/pipeline/tasks/{task_id}/cancel", status_code=200)
async def cancel_pipeline_task(task_id: str, _key: ApiKeyDep) -> dict:
    """Cancel a task. Only effective if still queued or pending human review."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tasks
            SET status = 'cancelled', completed_at = now()
            WHERE id = $1::uuid
              AND status IN ('queued', 'pending_human_review')
            """,
            task_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(
            status_code=409,
            detail="Task cannot be cancelled in its current state",
        )
    return {"task_id": task_id, "status": "cancelled"}


class ReviewDecisionRequest(BaseModel):
    decision: str           # "approve" | "reject"
    comment: str | None = None


@router.post("/api/v1/pipeline/tasks/{task_id}/review", status_code=200)
async def review_pending_task(
    task_id: str,
    req: ReviewDecisionRequest,
    _admin: AdminDep,
) -> dict:
    """
    Approve or reject a task paused in pending_human_review.

    approve — re-queues the task so it resumes from checkpoint and completes.
              Because all pipeline stages were checkpointed before pausing, the
              executor skips every agent and completes immediately at zero LLM cost.

    reject  — marks the task cancelled and records the reviewer's comment.

    Both paths write an audit log entry for the decision trail.
    """
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    pool = get_pool()

    if req.decision == "approve":
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tasks
                SET status    = 'queued',
                    metadata  = metadata || jsonb_build_object(
                        'human_approved_at', now()::text,
                        'human_comment',     $2::text
                    )
                WHERE id = $1::uuid AND status = 'pending_human_review'
                """,
                task_id, req.comment or "",
            )
        if result == "UPDATE 0":
            raise HTTPException(
                status_code=409,
                detail="Task is not in pending_human_review state",
            )
        await enqueue_task(task_id)
        log.info("Task %s approved by human reviewer — re-queued", task_id)

        # Audit trail
        pool2 = get_pool()
        async with pool2.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, severity, task_id, message, data)
                VALUES ('human_review_approved', 'info', $1::uuid, $2, $3::jsonb)
                """,
                task_id,
                "Human reviewer approved task — resuming from checkpoint",
                {"comment": req.comment},
            )

        return {"task_id": task_id, "status": "queued", "decision": "approve"}

    else:  # reject
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE tasks
                SET status       = 'cancelled',
                    completed_at = now(),
                    error        = $2,
                    metadata     = metadata || jsonb_build_object(
                        'human_rejected_at', now()::text,
                        'human_comment',     $2::text
                    )
                WHERE id = $1::uuid AND status = 'pending_human_review'
                """,
                task_id, req.comment or "Rejected by human reviewer",
            )
        if result == "UPDATE 0":
            raise HTTPException(
                status_code=409,
                detail="Task is not in pending_human_review state",
            )
        log.info("Task %s rejected by human reviewer", task_id)

        pool2 = get_pool()
        async with pool2.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (event_type, severity, task_id, message, data)
                VALUES ('human_review_rejected', 'warning', $1::uuid, $2, $3::jsonb)
                """,
                task_id,
                "Human reviewer rejected task — cancelled",
                {"comment": req.comment},
            )

        return {"task_id": task_id, "status": "cancelled", "decision": "reject"}


@router.get("/api/v1/pipeline/queue-stats")
async def queue_stats(_admin: AdminDep) -> dict:
    """Queue depth, dead-letter depth for ops visibility."""
    return {
        "queue_depth": await queue_depth(),
        "dead_letter_depth": await dead_letter_depth(),
    }


@router.get("/api/v1/pipeline/dead-letter")
async def get_dead_letter_tasks(
    _admin: AdminDep,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """List tasks in the dead-letter queue (exhausted all retries)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.status, t.user_input, t.error,
                   t.retry_count, t.max_retries,
                   t.queued_at, t.completed_at
            FROM tasks t
            WHERE t.status = 'failed'
            ORDER BY t.completed_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
        )
    return [dict(r) for r in rows]


# ── Pod endpoints ──────────────────────────────────────────────────────────────

@router.get("/api/v1/pods")
async def list_pods(_key: ApiKeyDep) -> list[dict]:
    """List all pods (enabled and disabled)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*,
                   COUNT(pa.id) FILTER (WHERE pa.enabled) AS active_agent_count
            FROM pods p
            LEFT JOIN pod_agents pa ON pa.pod_id = p.id
            GROUP BY p.id
            ORDER BY p.name
            """
        )
    return [dict(r) for r in rows]


@router.post("/api/v1/pods", status_code=201)
async def create_pod(req: PodRequest, _admin: AdminDep) -> dict:
    """Create a new pod configuration. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pods
                (name, description, enabled, routing_keywords, default_model,
                 max_cost_usd, max_execution_seconds, require_human_review,
                 escalation_threshold, metadata)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
            RETURNING *
            """,
            req.name, req.description, req.enabled,
            req.routing_keywords, req.default_model,
            req.max_cost_usd, req.max_execution_seconds,
            req.require_human_review, req.escalation_threshold,
            req.metadata,
        )
    return dict(row)


@router.get("/api/v1/pods/{pod_id}")
async def get_pod(pod_id: str, _key: ApiKeyDep) -> dict:
    """Get pod details including its agent list."""
    pool = get_pool()
    async with pool.acquire() as conn:
        pod = await conn.fetchrow("SELECT * FROM pods WHERE id = $1::uuid", pod_id)
        if not pod:
            raise HTTPException(status_code=404, detail="Pod not found")
        agents = await conn.fetch(
            "SELECT * FROM pod_agents WHERE pod_id = $1::uuid ORDER BY position",
            pod_id,
        )
    return {**dict(pod), "agents": [dict(a) for a in agents]}


@router.patch("/api/v1/pods/{pod_id}")
async def update_pod(pod_id: str, req: PodRequest, _admin: AdminDep) -> dict:
    """Update pod configuration. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE pods SET
                name                 = $2,
                description          = $3,
                enabled              = $4,
                routing_keywords     = $5,
                default_model        = $6,
                max_cost_usd         = $7,
                max_execution_seconds = $8,
                require_human_review = $9,
                escalation_threshold = $10,
                metadata             = $11::jsonb
            WHERE id = $1::uuid
            RETURNING *
            """,
            pod_id, req.name, req.description, req.enabled,
            req.routing_keywords, req.default_model,
            req.max_cost_usd, req.max_execution_seconds,
            req.require_human_review, req.escalation_threshold,
            req.metadata,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Pod not found")
    return dict(row)


@router.delete("/api/v1/pods/{pod_id}", status_code=204)
async def delete_pod(pod_id: str, _admin: AdminDep) -> None:
    """Delete a pod and all its agents. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM pods WHERE id = $1::uuid", pod_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Pod not found")


# ── Pod agent endpoints ────────────────────────────────────────────────────────

@router.get("/api/v1/pods/{pod_id}/agents")
async def list_pod_agents(pod_id: str, _key: ApiKeyDep) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM pod_agents WHERE pod_id = $1::uuid ORDER BY position",
            pod_id,
        )
    return [dict(r) for r in rows]


@router.post("/api/v1/pods/{pod_id}/agents", status_code=201)
async def add_pod_agent(pod_id: str, req: AgentRequest, _admin: AdminDep) -> dict:
    """Add an agent to a pod. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify pod exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pods WHERE id = $1::uuid", pod_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Pod not found")

        row = await conn.fetchrow(
            """
            INSERT INTO pod_agents
                (pod_id, name, role, enabled, position, parallel_group,
                 model, fallback_models, temperature, max_tokens, timeout_seconds,
                 max_retries, system_prompt, allowed_tools, on_failure,
                 run_condition, artifact_type)
            VALUES
                ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17)
            RETURNING *
            """,
            pod_id, req.name, req.role, req.enabled, req.position,
            req.parallel_group, req.model, req.fallback_models,
            req.temperature, req.max_tokens,
            req.timeout_seconds, req.max_retries, req.system_prompt,
            req.allowed_tools, req.on_failure,
            req.run_condition, req.artifact_type,
        )
    return dict(row)


@router.patch("/api/v1/pods/{pod_id}/agents/{agent_id}")
async def update_pod_agent(
    pod_id: str, agent_id: str, req: AgentRequest, _admin: AdminDep
) -> dict:
    """Update an agent's configuration. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE pod_agents SET
                name            = $3,
                role            = $4,
                enabled         = $5,
                position        = $6,
                parallel_group  = $7,
                model           = $8,
                fallback_models = $9,
                temperature     = $10,
                max_tokens      = $11,
                timeout_seconds = $12,
                max_retries     = $13,
                system_prompt   = $14,
                allowed_tools   = $15,
                on_failure      = $16,
                run_condition   = $17::jsonb,
                artifact_type   = $18
            WHERE id = $1::uuid AND pod_id = $2::uuid
            RETURNING *
            """,
            agent_id, pod_id, req.name, req.role, req.enabled, req.position,
            req.parallel_group, req.model, req.fallback_models,
            req.temperature, req.max_tokens,
            req.timeout_seconds, req.max_retries, req.system_prompt,
            req.allowed_tools, req.on_failure,
            req.run_condition, req.artifact_type,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found in this pod")
    return dict(row)


@router.delete("/api/v1/pods/{pod_id}/agents/{agent_id}", status_code=204)
async def delete_pod_agent(pod_id: str, agent_id: str, _admin: AdminDep) -> None:
    """Remove an agent from a pod. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM pod_agents WHERE id = $1::uuid AND pod_id = $2::uuid",
            agent_id, pod_id,
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Agent not found in this pod")


# ── MCP server management (admin-only) ────────────────────────────────────────

class MCPServerRequest(BaseModel):
    name: str
    description: str = ""
    transport: str = "stdio"          # "stdio" | "http"
    command: str | None = None        # stdio: executable to spawn
    args: list[str] = []              # stdio: argument list
    env: dict[str, str] = {}          # stdio: extra environment variables
    url: str | None = None            # http: server base URL
    enabled: bool = True
    metadata: dict[str, Any] = {}


def _mcp_row_to_dict(row) -> dict:
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat()
    d["args"] = list(d.get("args") or [])
    d["env"] = dict(d.get("env") or {})
    d["metadata"] = dict(d.get("metadata") or {})
    return d


@router.get("/api/v1/mcp-servers")
async def list_mcp_servers(_admin: AdminDep) -> list[dict]:
    """List all registered MCP servers with live connection status. Admin-only."""
    from app.pipeline.tools.registry import list_connected_servers

    connected_map = {s["name"]: s for s in list_connected_servers()}
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM mcp_servers ORDER BY name")

    result = []
    for row in rows:
        d = _mcp_row_to_dict(row)
        status = connected_map.get(d["name"])
        d["connected"]    = status["connected"]   if status else False
        d["tool_count"]   = status["tool_count"]  if status else 0
        d["active_tools"] = status["tools"]        if status else []
        result.append(d)
    return result


@router.post("/api/v1/mcp-servers", status_code=201)
async def create_mcp_server(req: MCPServerRequest, _admin: AdminDep) -> dict:
    """Register a new MCP server and immediately attempt to connect if enabled. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mcp_servers
                (name, description, transport, command, args, env, url, enabled, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9::jsonb)
            RETURNING *
            """,
            req.name, req.description, req.transport, req.command,
            req.args, req.env, req.url, req.enabled, req.metadata,
        )
    d = _mcp_row_to_dict(row)

    # Immediately attempt connection if enabled stdio server
    if req.enabled and req.transport == "stdio" and req.command:
        from app.pipeline.tools.registry import reload_mcp_server
        d["connected"] = await reload_mcp_server(req.name)
    else:
        d["connected"] = False
    d["tool_count"]   = 0
    d["active_tools"] = []
    return d


@router.patch("/api/v1/mcp-servers/{server_id}")
async def update_mcp_server(
    server_id: str, req: MCPServerRequest, _admin: AdminDep
) -> dict:
    """Update an MCP server's configuration. Triggers a reconnect. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE mcp_servers SET
                name        = $2,
                description = $3,
                transport   = $4,
                command     = $5,
                args        = $6::jsonb,
                env         = $7::jsonb,
                url         = $8,
                enabled     = $9,
                metadata    = $10::jsonb
            WHERE id = $1::uuid
            RETURNING *
            """,
            server_id, req.name, req.description, req.transport,
            req.command, req.args, req.env, req.url, req.enabled, req.metadata,
        )
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")
    d = _mcp_row_to_dict(row)

    # Reconnect with new config
    if req.enabled and req.transport == "stdio" and req.command:
        from app.pipeline.tools.registry import reload_mcp_server
        d["connected"] = await reload_mcp_server(req.name)
    else:
        from app.pipeline.tools.registry import disconnect_server
        await disconnect_server(req.name)
        d["connected"] = False
    return d


@router.delete("/api/v1/mcp-servers/{server_id}", status_code=204)
async def delete_mcp_server(server_id: str, _admin: AdminDep) -> None:
    """Remove an MCP server from the registry and disconnect it. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM mcp_servers WHERE id = $1::uuid RETURNING name",
            server_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    from app.pipeline.tools.registry import disconnect_server
    await disconnect_server(row["name"])


@router.post("/api/v1/mcp-servers/{server_id}/reload", status_code=200)
async def reload_mcp_server_endpoint(server_id: str, _admin: AdminDep) -> dict:
    """Reload (reconnect) an MCP server without restarting the orchestrator. Admin-only."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name FROM mcp_servers WHERE id = $1::uuid", server_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="MCP server not found")

    from app.pipeline.tools.registry import reload_mcp_server, list_connected_servers
    connected = await reload_mcp_server(row["name"])
    status = next(
        (s for s in list_connected_servers() if s["name"] == row["name"]),
        None,
    )
    return {
        "name": row["name"],
        "connected": connected,
        "tool_count": status["tool_count"] if status else 0,
        "tools": status["tools"] if status else [],
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _task_dict(row) -> dict:
    """Convert a task DB row to a JSON-serialisable dict."""
    d = dict(row)
    # Timestamps → ISO strings for clean JSON output
    for ts_field in ("queued_at", "started_at", "completed_at"):
        if d.get(ts_field) is not None:
            d[ts_field] = d[ts_field].isoformat()
    # Convert UUID to string
    d["id"] = str(d["id"]) if d.get("id") else None
    d["pod_id"] = str(d["pod_id"]) if d.get("pod_id") else None
    return d
