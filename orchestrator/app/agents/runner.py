"""
AgentRunner — executes a single agent turn:
  1. Retrieve relevant memories + live platform state (async, parallel)
  2. Build the prompt with token budget allocation
  3. Call LLM Gateway — handles tool-use loop internally until final answer
  4. Store new memories from the conversation
  5. Log usage (fire-and-forget — never blocks response)
  6. Return the response
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone
from uuid import UUID

from nova_contracts import (
    CompleteRequest,
    Message,
    TaskResult,
    TaskStatus,
    ToolCallRef,
)

from app.clients import get_llm_client, get_memory_client
from app.config import settings
from app.tools import ALL_TOOLS, execute_tool

log = logging.getLogger(__name__)


async def run_agent_turn(
    agent_id: str,
    task_id: UUID,
    session_id: str,
    messages: list[dict],
    model: str,
    system_prompt: str,
    api_key_id: UUID | None = None,
) -> TaskResult:
    """Execute one agent turn: memory retrieval → LLM call → memory storage → usage log."""
    from app.usage import log_usage

    started_at = datetime.now(timezone.utc)

    try:
        user_messages = [m for m in messages if m.get("role") == "user"]
        query = user_messages[-1]["content"] if user_messages else ""

        # 1. Fetch context concurrently
        import asyncio as _asyncio
        nova_ctx, memory_ctx = await _asyncio.gather(
            _build_nova_context(model, agent_id, session_id),
            _get_memory_context(agent_id, query),
        )

        # 2. Build prompt
        prompt_messages = _build_prompt(system_prompt, nova_ctx, memory_ctx, messages)

        # 3. LLM call with tool loop — returns 4-tuple now
        assistant_content, input_tokens, output_tokens, cost_usd = await _run_tool_loop(
            messages=prompt_messages,
            model=model,
            metadata={"agent_id": agent_id, "task_id": str(task_id), "session_id": session_id},
            tools=None,   # None → ALL_TOOLS for normal agent turns
        )

        # 4. Store exchange in episodic memory
        await _store_exchange(agent_id, session_id, query, assistant_content)

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        # 5. Log usage — fire-and-forget, no await
        log_usage(
            api_key_id=api_key_id,
            agent_id=UUID(agent_id),
            session_id=session_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
        )

        return TaskResult(
            task_id=task_id,
            agent_id=UUID(agent_id),
            status=TaskStatus.completed,
            response=assistant_content,
            started_at=started_at,
            completed_at=completed_at,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    except Exception as e:
        log.error("Agent turn failed for task %s: %s", task_id, e, exc_info=True)
        return TaskResult(
            task_id=task_id,
            agent_id=UUID(agent_id),
            status=TaskStatus.failed,
            error=str(e),
            started_at=started_at,
        )


async def run_agent_turn_streaming(
    agent_id: str,
    task_id: UUID,
    session_id: str,
    messages: list[dict],
    model: str,
    system_prompt: str,
    api_key_id: UUID | None = None,
):
    """Streaming variant — yields text deltas as they arrive from the LLM.

    Tool-use strategy: resolve tool-call rounds non-streaming (fast, tool calls
    rarely produce large output), then stream the final answer turn. This keeps
    the UI responsive without complex mid-stream interruption handling.

    Known Phase 2 limitation: token counts are 0 for streaming responses because
    StreamChunk carries no usage data. Usage event still writes for the audit trail.
    """
    from app.usage import log_usage
    import asyncio as _asyncio

    started_at = datetime.now(timezone.utc)
    user_messages = [m for m in messages if m.get("role") == "user"]
    query = user_messages[-1]["content"] if user_messages else ""

    nova_ctx, memory_ctx = await _asyncio.gather(
        _build_nova_context(model, agent_id, session_id),
        _get_memory_context(agent_id, query),
    )
    prompt_messages = _build_prompt(system_prompt, nova_ctx, memory_ctx, messages)

    streaming_messages, used_tools = await _resolve_tool_rounds(
        messages=prompt_messages,
        model=model,
        metadata={"agent_id": agent_id, "session_id": session_id},
    )

    # Pass tools when history contains tool interactions — Anthropic requires
    # tools= to be present whenever any message references tool_use content.
    llm_client = get_llm_client()
    complete_req = CompleteRequest(
        model=model,
        messages=streaming_messages,
        tools=ALL_TOOLS if used_tools else [],
        stream=True,
        metadata={"agent_id": agent_id, "session_id": session_id},
    )

    full_response: list[str] = []
    async with llm_client.stream("POST", "/stream", json=complete_req.model_dump()) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line or line == "data: [DONE]":
                continue
            if line.startswith("data: "):
                chunk_data = _json.loads(line[6:])
                if "error" in chunk_data:
                    raise RuntimeError(
                        f"LLM Gateway error ({chunk_data.get('provider', 'unknown')}): "
                        f"{chunk_data['error']}"
                    )
                delta = chunk_data.get("delta", "")
                if delta:
                    full_response.append(delta)
                    yield delta

    if full_response:
        await _store_exchange(agent_id, session_id, query, "".join(full_response))

    completed_at = datetime.now(timezone.utc)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    log_usage(
        api_key_id=api_key_id,
        agent_id=UUID(agent_id),
        session_id=session_id,
        model=model,
        input_tokens=0,    # not available from streaming chunks in Phase 2
        output_tokens=0,
        cost_usd=None,
        duration_ms=duration_ms,
    )


async def _get_memory_context(agent_id: str, query: str) -> str:
    """Fetch relevant memories and format them as a context string."""
    if not query:
        return ""

    memory_client = get_memory_client()
    try:
        resp = await memory_client.post(
            f"/api/v1/agents/{agent_id}/context",
            json={"agent_id": agent_id, "query": query, "max_tokens": 4096},
        )
        if resp.status_code != 200:
            return ""
        ctx = resp.json()
        memories = ctx.get("memories", [])
        if not memories:
            return ""

        lines = ["## Relevant memories from previous conversations:"]
        for m in memories:
            lines.append(f"- {m['content']}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("Memory retrieval failed: %s", e)
        return ""


async def _get_platform_persona() -> str:
    """
    Load the Nova persona from platform_config (nova.persona key).
    Returns empty string on any failure — missing table, bad value, etc.
    This is intentionally fault-tolerant: persona is a nice-to-have overlay,
    not load-bearing infrastructure.
    """
    import json as _json
    from app.db import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM platform_config WHERE key = 'nova.persona'"
            )
        if row and row["value"]:
            persona = _json.loads(row["value"])
            return str(persona).strip() if persona else ""
        return ""
    except Exception as exc:
        log.debug("Could not load nova.persona: %s", exc)
        return ""


async def _build_nova_context(model: str, agent_id: str, session_id: str) -> str:
    """
    Build the 'Nova Platform Context' block injected into every system prompt.
    Queries live agent state from Redis so the LLM knows what's actually running.

    Placement: after static system_prompt, before dynamic memories.
    This maximises Anthropic prompt cache hits (stable prefix = cheaper turns).

    Persona: loaded from platform_config and appended at the end so operators
    can customise Nova's communication style without touching operational instructions.
    """
    from app.store import list_agents

    try:
        all_agents = await list_agents()
        active = [a for a in all_agents if a.status.value != "stopped"]
        if active:
            agent_lines = []
            for a in sorted(active, key=lambda x: x.created_at):
                marker = " ← YOU" if str(a.id) == agent_id else ""
                agent_lines.append(
                    f"  • {a.config.name}  id={a.id}"
                    f"  model={a.config.model}  status={a.status.value}{marker}"
                )
            agents_block = "\n".join(agent_lines)
        else:
            agents_block = "  (none registered yet)"
    except Exception as e:
        log.warning("Could not fetch agent list for nova_context: %s", e)
        agents_block = "  (unavailable)"

    persona = await _get_platform_persona()
    persona_block = f"\n\n## Persona\n{persona}" if persona else ""

    return (
        f"## Nova Platform Context\n"
        f"- Your model:    {model}\n"
        f"- Your agent ID: {agent_id}\n"
        f"- Session ID:    {session_id}\n"
        f"\n### Active agents in this Nova instance:\n"
        f"{agents_block}\n"
        f"\n### Tools available to you:\n"
        f"  Platform:   list_agents, get_agent_info, create_agent, list_available_models, send_message_to_agent\n"
        f"  Filesystem: list_dir, read_file, write_file\n"
        f"  Shell:      run_shell (runs in workspace, hard timeout {settings.shell_timeout_seconds}s)\n"
        f"  Search:     search_codebase (ripgrep across workspace files)\n"
        f"  Git:        git_status, git_diff, git_log, git_commit\n"
        f"\nWorkspace root: {settings.workspace_root}  (all file/shell paths are relative to this)\n"
        f"Answer model-identity questions using 'Your model' above (never guess).\n"
        f"\n## Response Style\n"
        f"This is a professional developer tool. Follow these rules in every response:\n"
        f"- No emoji except as explicit status indicators (e.g. 🟢 active, 🟡 idle, 🔴 error)\n"
        f"- No markdown bold/italic for single characters or trivial emphasis\n"
        f"- Do not bold the word 'I' or wrap single letters in ** markers\n"
        f"- Use plain prose for explanations; tables for structured data; code blocks for code\n"
        f"- Be concise and precise — prefer one clear sentence over three vague ones\n"
        f"- Never add filler phrases like 'Great question!', 'Certainly!', or 'Of course!'"
        f"{persona_block}"
    )


async def _resolve_tool_rounds(
    messages: list[Message],
    model: str,
    metadata: dict,
    max_rounds: int = 5,
) -> tuple[list[Message], bool]:
    """
    Execute any tool-call rounds the LLM requests, returning the enriched
    message list ready for the final streaming turn.

    Returns (messages_with_tool_history, used_tools_flag).
    If the LLM makes no tool calls, returns the original messages immediately.
    """
    llm_client = get_llm_client()
    current = list(messages)
    used_tools = False

    for round_num in range(max_rounds):
        req = CompleteRequest(
            model=model,
            messages=current,
            tools=ALL_TOOLS,
            metadata=metadata,
        )
        resp = await llm_client.post("/complete", json=req.model_dump())
        resp.raise_for_status()
        completion = resp.json()

        tool_calls = completion.get("tool_calls", [])
        if not tool_calls:
            break

        used_tools = True
        log.info("Tool-use round %d: %d tool call(s)", round_num + 1, len(tool_calls))

        assistant_msg = Message(
            role="assistant",
            content=completion.get("content") or "",
            tool_calls=[
                ToolCallRef(id=tc["id"], name=tc["name"], arguments=tc.get("arguments", {}))
                for tc in tool_calls
            ],
        )
        current.append(assistant_msg)

        for tc in tool_calls:
            result = await execute_tool(tc["name"], tc.get("arguments", {}))
            current.append(Message(
                role="tool",
                name=tc["name"],
                tool_call_id=tc["id"],
                content=result,
            ))

    return current, used_tools


async def run_agent_turn_raw(
    system_prompt: str,
    user_message: str,
    model: str,
    tools: list | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    max_rounds: int = 10,
) -> str:
    """
    Lightweight agent turn for pipeline stages (ContextAgent, TaskAgent).

    Runs the full tool-use loop and returns the final assistant text.
    No memory retrieval/storage, no usage logging — the pipeline executor
    handles those concerns at the task level.

    Args:
        system_prompt:  Agent's system prompt
        user_message:   User request / constructed prompt
        model:          LLM model identifier (e.g. "llama3.2")
        tools:          Tool definitions to pass to the LLM.
                        None  → ALL_TOOLS  (full access)
                        []    → no tools   (text-only)
                        [...]  → explicit subset
        temperature:    Sampling temperature from pod_agents config
        max_tokens:     Max output tokens from pod_agents config
        max_rounds:     Max tool-use rounds before forcing a final answer

    Returns:
        The final assistant text response.
    """
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user",   content=user_message),
    ]
    content, _, _, _ = await _run_tool_loop(
        messages=messages,
        model=model,
        metadata={},
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
    )
    return content


async def _run_tool_loop(
    messages: list[Message],
    model: str,
    metadata: dict,
    tools: list | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_rounds: int = 5,
) -> tuple[str, int, int, float | None]:
    """
    Non-streaming tool loop — used by run_agent_turn and run_agent_turn_raw.
    Returns (content, input_tokens, output_tokens, cost_usd) from the final completion.
    Token counts come from the last LLM response in the loop.

    Args:
        tools:  None → ALL_TOOLS; [] → no tools; [...] → explicit subset.
    """
    effective_tools = ALL_TOOLS if tools is None else tools
    llm_client = get_llm_client()
    current = list(messages)
    last_completion: dict = {}

    for round_num in range(max_rounds):
        req = CompleteRequest(
            model=model,
            messages=current,
            tools=effective_tools,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata=metadata,
        )
        resp = await llm_client.post("/complete", json=req.model_dump())
        resp.raise_for_status()
        last_completion = resp.json()

        tool_calls = last_completion.get("tool_calls", [])
        if not tool_calls:
            break

        log.info("Tool-use round %d: %d tool call(s)", round_num + 1, len(tool_calls))

        assistant_msg = Message(
            role="assistant",
            content=last_completion.get("content") or "",
            tool_calls=[
                ToolCallRef(id=tc["id"], name=tc["name"], arguments=tc.get("arguments", {}))
                for tc in tool_calls
            ],
        )
        current.append(assistant_msg)

        for tc in tool_calls:
            result = await execute_tool(tc["name"], tc.get("arguments", {}))
            current.append(Message(
                role="tool",
                name=tc["name"],
                tool_call_id=tc["id"],
                content=result,
            ))

    return (
        last_completion.get("content", ""),
        last_completion.get("input_tokens", 0),
        last_completion.get("output_tokens", 0),
        last_completion.get("cost_usd"),
    )


def _build_prompt(
    system_prompt: str,
    nova_context: str,
    memory_context: str,
    messages: list[dict],
) -> list[Message]:
    """
    Assemble the full message list with context injected.

    System prompt order (static → dynamic for best prompt cache hit rate):
      1. Base system_prompt  — stable across all turns of a session
      2. Nova context block  — stable per session (model + agent/session IDs)
      3. Memory context      — dynamic, changes as memories accumulate
    """
    sections = [system_prompt, nova_context]
    if memory_context:
        sections.append(memory_context)
    full_system = "\n\n".join(sections)

    result = [Message(role="system", content=full_system)]
    for m in messages:
        result.append(Message(role=m["role"], content=m["content"]))

    return result


async def _store_exchange(
    agent_id: str,
    session_id: str,
    user_message: str,
    assistant_response: str,
) -> None:
    """Store user message and assistant response as episodic memories."""
    memory_client = get_memory_client()
    try:
        memories = [
            {
                "agent_id": agent_id,
                "content": f"User: {user_message}",
                "tier": "episodic",
                "metadata": {"session_id": session_id, "role": "user"},
            },
            {
                "agent_id": agent_id,
                "content": f"Assistant: {assistant_response}",
                "tier": "episodic",
                "metadata": {"session_id": session_id, "role": "assistant"},
            },
        ]
        await memory_client.post("/api/v1/memories/bulk", json={"memories": memories})
    except Exception as e:
        log.warning("Failed to store conversation memories: %s", e)
