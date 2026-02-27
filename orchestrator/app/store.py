"""
Agent and task state store backed by Redis.
The Orchestrator is stateless — all state lives in Redis.
This allows horizontal scaling and crash recovery.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from nova_contracts import AgentConfig, AgentInfo, AgentStatus, TaskResult, TaskStatus

from app.config import settings

log = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

AGENT_KEY = "nova:agent:{agent_id}"
TASK_KEY = "nova:task:{task_id}"
AGENT_TASKS_KEY = "nova:agent:{agent_id}:tasks"


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def create_agent(config: AgentConfig) -> AgentInfo:
    agent_id = str(uuid4())
    now = datetime.utcnow()
    info = AgentInfo(
        id=UUID(agent_id),
        config=config,
        status=AgentStatus.idle,
        created_at=now,
    )
    redis = get_redis()
    await redis.set(
        AGENT_KEY.format(agent_id=agent_id),
        info.model_dump_json(),
    )
    log.info("Created agent %s (%s)", agent_id, config.name)
    return info


async def get_agent(agent_id: str) -> AgentInfo | None:
    redis = get_redis()
    data = await redis.get(AGENT_KEY.format(agent_id=agent_id))
    if not data:
        return None
    return AgentInfo.model_validate_json(data)


async def update_agent_status(agent_id: str, status: AgentStatus) -> None:
    agent = await get_agent(agent_id)
    if not agent:
        return
    agent.status = status
    agent.last_active = datetime.utcnow()
    redis = get_redis()
    await redis.set(AGENT_KEY.format(agent_id=agent_id), agent.model_dump_json())


async def list_agents() -> list[AgentInfo]:
    redis = get_redis()
    keys = await redis.keys("nova:agent:*")
    # Filter out task-related keys
    agent_keys = [k for k in keys if not any(s in k for s in [":tasks", ":task"])]
    if not agent_keys:
        return []
    values = await redis.mget(*agent_keys)
    agents = []
    for v in values:
        if v:
            try:
                agents.append(AgentInfo.model_validate_json(v))
            except Exception:
                pass
    return agents


async def store_task_result(result: TaskResult) -> None:
    redis = get_redis()
    task_id = str(result.task_id)
    agent_id = str(result.agent_id)
    await redis.set(
        TASK_KEY.format(task_id=task_id),
        result.model_dump_json(),
        ex=86400,  # Tasks expire after 24h
    )
    await redis.lpush(AGENT_TASKS_KEY.format(agent_id=agent_id), task_id)
    await redis.ltrim(AGENT_TASKS_KEY.format(agent_id=agent_id), 0, 99)  # Keep last 100 tasks


async def get_task_result(task_id: str) -> TaskResult | None:
    redis = get_redis()
    data = await redis.get(TASK_KEY.format(task_id=task_id))
    if not data:
        return None
    return TaskResult.model_validate_json(data)


async def delete_agent(agent_id: str) -> bool:
    """Permanently remove an agent from Redis. Returns True if it existed."""
    redis = get_redis()
    key = AGENT_KEY.format(agent_id=agent_id)
    deleted = await redis.delete(key)
    if deleted:
        log.info("Deleted agent %s", agent_id)
    return bool(deleted)


async def update_agent_config(
    agent_id: str,
    *,
    model: str | None,
    system_prompt: str | None,
    fallback_models: list[str],
) -> AgentInfo | None:
    """
    Update an agent's model, system_prompt, and fallback_models in Redis.

    ``model=None`` means keep the current model.
    ``system_prompt`` is only written when it is a non-empty string.
    ``fallback_models`` replaces the entire list (pass [] to clear).
    """
    agent = await get_agent(agent_id)
    if not agent:
        return None
    if model:
        agent.config.model = model
    if system_prompt:
        agent.config.system_prompt = system_prompt
    agent.config.fallback_models = fallback_models
    agent.last_active = datetime.utcnow()
    redis = get_redis()
    await redis.set(AGENT_KEY.format(agent_id=agent_id), agent.model_dump_json())
    log.info("Updated config for agent %s (%s)", agent_id, agent.config.name)
    return agent


async def recover_stale_agents() -> int:
    """Reset any agents stuck in 'running' state back to 'idle'.

    Called on orchestrator startup. An agent left in 'running' means the
    process was killed mid-task — the task is gone, so the agent must be
    recovered to accept new work. Returns the count of agents recovered.
    """
    agents = await list_agents()
    recovered = 0
    for agent in agents:
        if agent.status == AgentStatus.running:
            await update_agent_status(str(agent.id), AgentStatus.idle)
            log.warning(
                "Recovered stale agent %s (%s) from running → idle",
                agent.id, agent.config.name,
            )
            recovered += 1
    if recovered:
        log.info("Startup recovery: reset %d stale agent(s) to idle", recovered)
    return recovered


async def ensure_primary_agent() -> AgentInfo:
    """Guarantee exactly one primary Nova agent exists with the configured model.

    Called at startup. If a non-stopped agent matching (name, model) already
    exists, it's returned as-is. Otherwise one is created. This replaces the
    pattern of manually creating agents — the primary agent is always there.
    """
    from nova_contracts import AgentConfig
    from app.config import settings

    agents = await list_agents()
    active = [
        a for a in agents
        if a.status != AgentStatus.stopped
        and a.config.name == settings.primary_agent_name
        and a.config.model == settings.default_model
    ]
    if active:
        # Use the most recently active one; clean up any extras
        active.sort(key=lambda a: a.last_active or a.created_at, reverse=True)
        primary = active[0]
        for dupe in active[1:]:
            await delete_agent(str(dupe.id))
            log.info("Removed duplicate primary agent %s", dupe.id)
        log.info("Primary agent found: %s (%s)", primary.id, primary.config.model)
        return primary

    config = AgentConfig(
        name=settings.primary_agent_name,
        model=settings.default_model,
        system_prompt=settings.default_system_prompt,
    )
    agent = await create_agent(config)
    log.info("Created primary agent %s (%s)", agent.id, agent.config.model)
    return agent
