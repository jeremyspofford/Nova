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

import asyncio
import json
import logging
import time
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
from app.tools import ALL_TOOLS, execute_tool, get_all_tools

log = logging.getLogger(__name__)


async def run_agent_turn(
    agent_id: str,
    task_id: UUID,
    session_id: str,
    messages: list[dict],
    model: str,
    system_prompt: str,
    api_key_id: UUID | None = None,
    explicit_model: bool = False,
) -> TaskResult:
    """Execute one agent turn: memory retrieval → LLM call → memory storage → usage log."""
    from app.usage import log_usage

    started_at = datetime.now(timezone.utc)

    try:
        from nova_contracts import extract_text_content

        user_messages = [m for m in messages if m.get("role") == "user"]
        query = extract_text_content(user_messages[-1]["content"]) if user_messages else ""

        # 1. Fetch context concurrently (+ intelligent routing when auto-model)
        from app.model_classifier import classify_and_resolve

        async def _noop_classify():
            return (None, None)

        classify_coro = classify_and_resolve(query) if (not explicit_model and query) else _noop_classify()

        nova_ctx, (memory_ctx, _mem_count), (category, classified_model) = await asyncio.gather(
            _build_nova_context(model, agent_id, session_id),
            _get_memory_context(agent_id, query),
            classify_coro,
        )

        if classified_model:
            model = classified_model

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
    skip_tool_preresolution: bool = False,
    explicit_model: bool = False,
    guest_mode: bool = False,
):
    """Streaming variant — yields text deltas as they arrive from the LLM.

    Tool-use strategy: by default, resolve tool-call rounds non-streaming
    (fast, tool calls rarely produce large output), then stream the final
    answer turn.

    When skip_tool_preresolution=True (used by interactive chat), tools are
    passed directly to the streaming call — the model can use them inline
    without an extra non-streaming round-trip. This cuts first-token latency
    roughly in half for conversational messages.

    When guest_mode=True, context retrieval (nova_context, memory) and tools
    are skipped entirely — the model receives only the system prompt and user
    messages with no platform state or tool access.
    """
    from app.usage import log_usage

    from nova_contracts import extract_text_content

    started_at = datetime.now(timezone.utc)
    user_messages = [m for m in messages if m.get("role") == "user"]
    query = extract_text_content(user_messages[-1]["content"]) if user_messages else ""

    category = None

    if guest_mode:
        # Guest isolation: no context, no memory, no tools, no classification
        nova_ctx = ""
        memory_ctx = ""
        memory_count = 0
        yield json.dumps({"status": {"step": "model", "state": "done", "detail": model}})
    else:
        # Intelligent routing: classify in parallel with context retrieval
        from app.model_classifier import classify_and_resolve

        will_classify = not explicit_model and query

        async def _noop_classify():
            return (None, None)

        classify_coro = classify_and_resolve(query) if will_classify else _noop_classify()

        # Emit "running" status for parallel steps before the gather
        if will_classify:
            yield json.dumps({"status": {"step": "classifying", "state": "running"}})
        yield json.dumps({"status": {"step": "memory", "state": "running"}})

        # Wrap coroutines to track individual timings
        async def _timed(coro):
            t = time.monotonic()
            result = await coro
            return result, int((time.monotonic() - t) * 1000)

        (nova_ctx, _ctx_ms), ((memory_ctx, memory_count), mem_ms), ((category, classified_model), cls_ms) = await asyncio.gather(
            _timed(_build_nova_context(model, agent_id, session_id)),
            _timed(_get_memory_context(agent_id, query)),
            _timed(classify_coro),
        )

        # Emit "done" status with per-step timings
        if will_classify:
            yield json.dumps({"status": {"step": "classifying", "state": "done", "detail": category or "general", "elapsed_ms": cls_ms}})
        mem_detail = f"{memory_count} memor{'y' if memory_count == 1 else 'ies'}" if memory_count else "no memories"
        yield json.dumps({"status": {"step": "memory", "state": "done", "detail": mem_detail, "elapsed_ms": mem_ms}})

        if classified_model:
            model = classified_model

        # Emit model selection status
        yield json.dumps({"status": {"step": "model", "state": "done", "detail": model}})

    prompt_messages = _build_prompt(system_prompt, nova_ctx, memory_ctx, messages)

    if guest_mode:
        # Guest mode: no tools at all
        streaming_messages = prompt_messages
        used_tools = False
    elif skip_tool_preresolution:
        # Pass tools directly to streaming — no pre-flight LLM call
        streaming_messages = prompt_messages
        used_tools = True  # Always include tools so model can use them
    else:
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
        tools=get_all_tools() if used_tools else [],
        stream=True,
        metadata={"agent_id": agent_id, "session_id": session_id},
    )

    # Emit generating status (replaces old meta event — info is carried by status steps)
    yield json.dumps({"status": {"step": "generating", "state": "running", "model": model, "category": category}})

    full_response: list[str] = []
    stream_input_tokens = 0
    stream_output_tokens = 0
    stream_cost_usd: float | None = None
    async with llm_client.stream("POST", "/stream", json=complete_req.model_dump()) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line or line == "data: [DONE]":
                continue
            if line.startswith("data: "):
                chunk_data = json.loads(line[6:])
                if "error" in chunk_data:
                    raise RuntimeError(
                        f"LLM Gateway error ({chunk_data.get('provider', 'unknown')}): "
                        f"{chunk_data['error']}"
                    )
                delta = chunk_data.get("delta", "")
                if delta:
                    full_response.append(delta)
                    yield delta
                # Capture token counts from the final chunk (sent by providers)
                if chunk_data.get("input_tokens") is not None:
                    stream_input_tokens = chunk_data["input_tokens"]
                if chunk_data.get("output_tokens") is not None:
                    stream_output_tokens = chunk_data["output_tokens"]
                if chunk_data.get("cost_usd") is not None:
                    stream_cost_usd = chunk_data["cost_usd"]

    if full_response:
        await _store_exchange(agent_id, session_id, query, "".join(full_response))

    completed_at = datetime.now(timezone.utc)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    log_usage(
        api_key_id=api_key_id,
        agent_id=UUID(agent_id),
        session_id=session_id,
        model=model,
        input_tokens=stream_input_tokens,
        output_tokens=stream_output_tokens,
        cost_usd=stream_cost_usd,
        duration_ms=duration_ms,
    )


async def _get_memory_context(agent_id: str, query: str) -> tuple[str, int]:
    """Fetch relevant memories and format them as a context string.

    Returns (context_string, memory_count).
    """
    if not query:
        return "", 0

    memory_client = get_memory_client()
    try:
        resp = await memory_client.post(
            f"/api/v1/agents/{agent_id}/context",
            json={"agent_id": agent_id, "query": query, "max_tokens": 4096},
        )
        if resp.status_code != 200:
            return "", 0
        ctx = resp.json()
        memories = ctx.get("memories", [])
        if not memories:
            return "", 0

        lines = ["## Relevant memories from previous conversations:"]
        for m in memories:
            lines.append(f"- {m['content']}")
        return "\n".join(lines), len(memories)
    except Exception as e:
        log.warning("Memory retrieval failed: %s", e)
        return "", 0


async def _get_platform_identity() -> tuple[str, str]:
    """
    Load the AI name and persona from platform_config.
    Returns (name, persona). Defaults to ("Nova", "") on any failure.
    """
    from app.db import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value #>> '{}' AS val "
                "FROM platform_config WHERE key IN ('nova.name', 'nova.persona')"
            )
        result = {r["key"]: r["val"] for r in rows}
        raw_name = result.get("nova.name") or "Nova"
        raw_persona = result.get("nova.persona") or ""
        # Strip one layer of JSON quoting if double-encoded
        name = json.loads(raw_name) if raw_name.startswith('"') else raw_name
        persona = json.loads(raw_persona) if raw_persona.startswith('"') else raw_persona
        return str(name).strip(), str(persona).strip()
    except Exception as exc:
        log.debug("Could not load platform identity: %s", exc)
        return "Nova", ""


async def _safe_list_agents(agent_id: str) -> str:
    """Format the active agents list, returning a safe fallback on error."""
    from app.store import list_agents
    try:
        all_agents = await list_agents()
        active = [a for a in all_agents if a.status.value != "stopped"]
        if active:
            lines = []
            for a in sorted(active, key=lambda x: x.created_at):
                marker = " <- YOU" if str(a.id) == agent_id else ""
                lines.append(
                    f"  - {a.config.name}  id={a.id}"
                    f"  model={a.config.model}  status={a.status.value}{marker}"
                )
            return "\n".join(lines)
        return "  (none registered yet)"
    except Exception as e:
        log.warning("Could not fetch agent list for nova_context: %s", e)
        return "  (unavailable)"


async def _build_nova_context(model: str, agent_id: str, session_id: str) -> str:
    """
    Build the context blocks injected into every system prompt.

    Order (static -> dynamic for prompt cache hit rate):
      1. ## Identity        - name + persona from platform_config
      2. ## Platform Context - tools, active agents, session info
      3. ## Response Style   - formatting rules
    """
    # Load identity and agent list concurrently
    (name, persona), agents_block = await asyncio.gather(
        _get_platform_identity(),
        _safe_list_agents(agent_id),
    )

    # 1. Identity block
    identity_lines = [
        "## Identity",
        f"Your name is {name}. You are a helpful AI assistant with persistent memory.",
        "You remember previous conversations and can use tools to help users.",
    ]
    if persona:
        identity_lines.append("")
        identity_lines.append(persona)
    identity_block = "\n".join(identity_lines)

    # 2. Platform context
    platform_block = (
        f"## Platform Context\n"
        f"- Your model:    {model}\n"
        f"- Your agent ID: {agent_id}\n"
        f"- Session ID:    {session_id}\n"
        f"\n### Active agents in this instance:\n"
        f"{agents_block}\n"
        f"\n### Tools available to you:\n"
        f"  Platform:   list_agents, get_agent_info, create_agent, list_available_models, send_message_to_agent\n"
        f"  Filesystem: list_dir, read_file, write_file\n"
        f"  Shell:      run_shell (runs in workspace, hard timeout {settings.shell_timeout_seconds}s)\n"
        f"  Search:     search_codebase (ripgrep across workspace files)\n"
        f"  Git:        git_status, git_diff, git_log, git_commit\n"
        f"\nWorkspace root: {settings.workspace_root}  (all file/shell paths are relative to this)\n"
        f"Answer model-identity questions using 'Your model' above (never guess)."
    )

    # 3. Response style
    style_block = (
        "## Response Style\n"
        "This is a professional developer tool. Follow these rules in every response:\n"
        "- No emoji except as explicit status indicators\n"
        "- No markdown bold/italic for single characters or trivial emphasis\n"
        "- Do not bold the word 'I' or wrap single letters in ** markers\n"
        "- Use plain prose for explanations; tables for structured data; code blocks for code\n"
        "- Be concise and precise - prefer one clear sentence over three vague ones\n"
        "- Never add filler phrases like 'Great question!', 'Certainly!', or 'Of course!'"
    )

    return f"{identity_block}\n\n{platform_block}\n\n{style_block}"


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
    Delegates to _run_tool_loop and discards token counts.
    """
    content, _, _, _, current, used_tools = await _run_tool_loop(
        messages=messages,
        model=model,
        metadata=metadata,
        tools=None,
        max_rounds=max_rounds,
        return_messages=True,
    )
    return current, used_tools


async def run_agent_turn_raw(
    system_prompt: str,
    user_message: str,
    model: str,
    tools: list | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    max_rounds: int = 10,
    return_usage: bool = False,
) -> str | tuple[str, int, int, float | None]:
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
        return_usage:   If True, returns (content, in_tokens, out_tokens, cost_usd)

    Returns:
        The final assistant text response, or a tuple with usage if return_usage=True.
    """
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user",   content=user_message),
    ]
    content, in_tokens, out_tokens, cost_usd = await _run_tool_loop(
        messages=messages,
        model=model,
        metadata={},
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
        max_rounds=max_rounds,
    )
    if return_usage:
        return content, in_tokens, out_tokens, cost_usd
    return content


async def _run_tool_loop(
    messages: list[Message],
    model: str,
    metadata: dict,
    tools: list | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_rounds: int = 5,
    return_messages: bool = False,
) -> tuple[str, int, int, float | None] | tuple[str, int, int, float | None, list[Message], bool]:
    """
    Non-streaming tool loop — used by run_agent_turn, run_agent_turn_raw, and _resolve_tool_rounds.
    Returns (content, input_tokens, output_tokens, cost_usd) from the final completion.
    When return_messages=True, also returns (messages, used_tools) for streaming pre-resolution.

    Args:
        tools:  None → ALL_TOOLS; [] → no tools; [...] → explicit subset.
    """
    effective_tools = get_all_tools() if tools is None else tools
    llm_client = get_llm_client()
    current = list(messages)
    last_completion: dict = {}
    used_tools = False

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

        used_tools = True
        log.info("Tool-use round %d: %d tool call(s)", round_num + 1, len(tool_calls))

        # Set assistant content from completion before delegating to helper
        current.append(Message(
            role="assistant",
            content=last_completion.get("content") or "",
            tool_calls=[
                ToolCallRef(id=tc["id"], name=tc["name"], arguments=tc.get("arguments", {}))
                for tc in tool_calls
            ],
        ))

        for tc in tool_calls:
            result = await execute_tool(tc["name"], tc.get("arguments", {}))
            current.append(Message(
                role="tool",
                name=tc["name"],
                tool_call_id=tc["id"],
                content=result,
            ))

    base = (
        last_completion.get("content", ""),
        last_completion.get("input_tokens", 0),
        last_completion.get("output_tokens", 0),
        last_completion.get("cost_usd"),
    )
    if return_messages:
        return base + (current, used_tools)
    return base


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
