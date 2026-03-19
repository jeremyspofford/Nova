"""
Platform Tools — what the Nova agent can DO inside the platform.

These are the LLM's eyes and hands into the Nova system. Each ToolDefinition
is what the LLM sees when deciding to call a tool; each execute_* function
is what actually runs when the LLM's request lands.

Adding a new tool:
  1. Add a ToolDefinition to PLATFORM_TOOLS (the LLM sees this description)
  2. Add a case in execute_tool()
  3. Implement the async execute_* function

Tool results are always returned as plain strings — the LLM receives them as
the content of a role="tool" message in the next turn.
"""
from __future__ import annotations

import logging

from nova_contracts import ToolDefinition

log = logging.getLogger(__name__)

# ─── Tool definitions (what the LLM sees) ────────────────────────────────────

PLATFORM_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="list_agents",
        description=(
            "List all agents currently registered in the Nova platform. "
            "Returns each agent's ID, name, model, status, and creation time."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolDefinition(
        name="get_agent_info",
        description="Get detailed configuration and status for a specific Nova agent.",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the agent to look up",
                }
            },
            "required": ["agent_id"],
        },
    ),
    ToolDefinition(
        name="create_agent",
        description=(
            "Create a new agent in the Nova platform with a given model and system prompt. "
            "Returns the new agent's ID. Use list_available_models to pick a model."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the agent (e.g. 'Research Assistant')",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Model ID, e.g. 'claude-max/claude-sonnet-4-6' or 'groq/llama-3.3-70b-versatile'. "
                        "Call list_available_models to see all options."
                    ),
                },
                "system_prompt": {
                    "type": "string",
                    "description": "System prompt defining the agent's role and behaviour",
                },
            },
            "required": ["name", "model", "system_prompt"],
        },
    ),
    ToolDefinition(
        name="list_available_models",
        description=(
            "List all LLM model IDs available in the Nova gateway, grouped by provider. "
            "Use this to pick a model when creating agents or switching models."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    ToolDefinition(
        name="send_message_to_agent",
        description=(
            "Send a message to another Nova agent and receive its response. "
            "Useful for delegating subtasks, getting specialist opinions, or "
            "orchestrating multi-agent workflows."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the target agent",
                },
                "message": {
                    "type": "string",
                    "description": "The message to send to the agent",
                },
            },
            "required": ["agent_id", "message"],
        },
    ),
    ToolDefinition(
        name="create_task",
        description=(
            "Submit a task to a pipeline pod for autonomous execution. Use this when the user's "
            "request requires multi-step code changes, thorough analysis, or work that benefits "
            "from the full pipeline (context gathering, guardrails, code review). Returns a task "
            "ID — the user will be notified when it completes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Clear description of what to accomplish",
                },
                "pod_name": {
                    "type": "string",
                    "description": "Target pod name (default: system default pod, usually 'Quartet')",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context to include (code snippets, file paths, constraints)",
                },
            },
            "required": ["description"],
        },
    ),
]


# ─── Tool execution ───────────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call by name and return its string result.

    Results are fed back to the LLM as the content of a role=tool message,
    so always return a human-readable string even on errors.
    """
    log.info("Executing platform tool: %s  args=%s", name, arguments)
    try:
        if name == "list_agents":
            return await _execute_list_agents()
        elif name == "get_agent_info":
            return await _execute_get_agent_info(arguments.get("agent_id", ""))
        elif name == "create_agent":
            return await _execute_create_agent(
                name=arguments["name"],
                model=arguments["model"],
                system_prompt=arguments["system_prompt"],
            )
        elif name == "list_available_models":
            return _execute_list_available_models()
        elif name == "send_message_to_agent":
            return await _execute_send_message_to_agent(
                agent_id=arguments["agent_id"],
                message=arguments["message"],
            )
        elif name == "create_task":
            return await _execute_create_task(
                description=arguments["description"],
                pod_name=arguments.get("pod_name"),
                context=arguments.get("context"),
            )
        else:
            return f"Unknown tool '{name}'. Available: {[t.name for t in PLATFORM_TOOLS]}"
    except Exception as e:
        log.error("Tool %s failed: %s", name, e, exc_info=True)
        return f"Tool '{name}' failed: {e}"


async def _execute_list_agents() -> str:
    from app.store import list_agents
    agents = await list_agents()
    if not agents:
        return "No agents currently registered in Nova."
    lines = ["Agents in Nova:"]
    for a in sorted(agents, key=lambda x: x.created_at):
        lines.append(
            f"  • {a.config.name}  id={a.id}  model={a.config.model}"
            f"  status={a.status.value}  created={a.created_at.strftime('%H:%M:%S')}"
        )
    return "\n".join(lines)


async def _execute_get_agent_info(agent_id: str) -> str:
    from app.store import get_agent
    agent = await get_agent(agent_id)
    if not agent:
        return f"Agent {agent_id!r} not found."
    return (
        f"Agent: {agent.config.name}\n"
        f"  ID:           {agent.id}\n"
        f"  Model:        {agent.config.model}\n"
        f"  Status:       {agent.status.value}\n"
        f"  Memory tiers: {', '.join(agent.config.memory_tiers)}\n"
        f"  Max tokens:   {agent.config.max_context_tokens}\n"
        f"  Tools:        {', '.join(agent.config.tools) or 'none'}\n"
        f"  System prompt (first 200 chars): {agent.config.system_prompt[:200]}"
    )


async def _execute_create_agent(name: str, model: str, system_prompt: str) -> str:
    from app.store import create_agent
    from nova_contracts import AgentConfig
    config = AgentConfig(name=name, model=model, system_prompt=system_prompt)
    agent = await create_agent(config)
    return (
        f"Created agent '{name}' successfully.\n"
        f"  ID:    {agent.id}\n"
        f"  Model: {model}\n"
        f"Use send_message_to_agent with id={agent.id} to interact with it."
    )


def _execute_list_available_models() -> str:
    """Return a curated list of model IDs from the gateway registry."""
    return """\
Available models by provider:

  Ollama (local, unlimited):
    llama3.2, llama3.1, mistral, phi4, qwen2.5, deepseek-r1, gemma3

  Claude Max subscription (fast, high-quality):
    claude-max/claude-sonnet-4-6   ← recommended default
    claude-max/claude-opus-4-6     ← most capable
    claude-max/claude-haiku-4-5    ← fastest, cheapest

  Groq (free API, 14 400 req/day):
    groq/llama-3.3-70b-versatile
    groq/llama-3.1-8b-instant

  Cerebras (free API, 1M tok/day):
    cerebras/llama3.1-8b

  Gemini (free API, 250 req/day):
    gemini/gemini-2.5-flash
    gemini/gemini-2.5-pro

  OpenRouter (free tier):
    openrouter/meta-llama/llama-3.1-8b-instruct:free

Use model IDs exactly as shown when calling create_agent."""


async def _execute_send_message_to_agent(agent_id: str, message: str) -> str:
    """Send one message to another agent and return its response.

    This is synchronous from the calling agent's perspective — it blocks until
    the target agent responds, which keeps the conversation coherent.
    Uses the orchestrator's own HTTP client so it goes through the full
    agent pipeline (memory retrieval, system prompt, etc.).
    """
    from uuid import uuid4
    from app.clients import get_orchestrator_client

    client = get_orchestrator_client()
    try:
        resp = await client.post(
            "/api/v1/tasks",
            json={
                "agent_id": agent_id,
                "session_id": f"cross-agent-{uuid4()}",
                "messages": [{"role": "user", "content": message}],
            },
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") == "failed":
            return f"Agent {agent_id} failed: {result.get('error', 'unknown error')}"
        return result.get("response", "(no response)")
    except Exception as e:
        return f"Failed to reach agent {agent_id}: {e}"


async def _execute_create_task(
    description: str,
    pod_name: str | None = None,
    context: str | None = None,
) -> str:
    """Submit a task to a pipeline pod for autonomous execution."""
    import json as _json
    from uuid import uuid4
    from app.db import get_pool
    from app.queue import enqueue_task

    pool = get_pool()

    # Resolve the target pod
    if pod_name:
        row = await pool.fetchrow(
            "SELECT id, name FROM pods WHERE name = $1 AND enabled = true",
            pod_name,
        )
        if not row:
            available = await pool.fetch(
                "SELECT name FROM pods WHERE enabled = true ORDER BY name"
            )
            names = [r["name"] for r in available]
            return (
                f"Pod '{pod_name}' not found or disabled. "
                f"Available pods: {', '.join(names) or 'none'}"
            )
    else:
        row = await pool.fetchrow(
            "SELECT id, name FROM pods WHERE is_system_default = true LIMIT 1"
        )
        if not row:
            return "No system default pod configured. Specify a pod_name explicitly."
        pod_name = row["name"]

    pod_id = str(row["id"])

    # Build task input
    user_input = description
    if context:
        user_input = f"{description}\n\nAdditional context:\n{context}"

    task_id = str(uuid4())
    metadata = _json.dumps({"source": "chat"})

    await pool.execute(
        """
        INSERT INTO tasks (id, user_input, pod_id, status, metadata, created_at)
        VALUES ($1::uuid, $2, $3::uuid, 'submitted', $4::jsonb, now())
        """,
        task_id,
        user_input,
        pod_id,
        metadata,
    )

    await enqueue_task(task_id)

    return (
        f"Task submitted to pod '{pod_name}' (ID: {task_id}). "
        f"The pipeline will execute this autonomously — you'll be notified when it completes."
    )
