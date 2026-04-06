"""Per-dimension quality scoring for chat responses.

Called by chat_scorer.py after each assistant turn. Each score_* function
returns a dict with {dimension, score, confidence, metadata} or None if
no signal for this turn.
"""
import re
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

MEMORY_SERVICE = "http://memory-service:8002"
LLM_GATEWAY = "http://llm-gateway:8001"

# Patterns that suggest the user is correcting Nova's memory
CORRECTION_PATTERNS = [
    re.compile(r"\bi\s+(already|just)\s+(told|said|mentioned)\b", re.I),
    re.compile(r"\bremember\s+when\s+i\b", re.I),
    re.compile(r"\bno,?\s+(it'?s|that'?s|i)\b", re.I),
    re.compile(r"\blike\s+i\s+(said|mentioned)\b", re.I),
    re.compile(r"\bi\s+already\s+explained\b", re.I),
    re.compile(r"\bthat'?s\s+(not|wrong)\b", re.I),
]


async def score_memory_relevance(
    engram_ids: list[str],
    query_text: str,
) -> dict[str, Any] | None:
    """Score how relevant retrieved engrams were to the user's query.

    Fetches engram content via batch endpoint, embeds both query and
    engram texts, computes average cosine similarity.
    """
    if not engram_ids:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch engram content
            batch_r = await client.post(
                f"{MEMORY_SERVICE}/api/v1/engrams/batch",
                json={"ids": engram_ids},
            )
            if batch_r.status_code != 200 or not batch_r.json():
                return None
            engrams = batch_r.json()

            # Embed query (gateway contract: texts=list, response has embeddings=list[list])
            query_embed_r = await client.post(
                f"{LLM_GATEWAY}/embed",
                json={"model": "auto", "texts": [query_text]},
            )
            if query_embed_r.status_code != 200:
                return None
            query_vec = (query_embed_r.json().get("embeddings") or [[]])[0]
            if not query_vec:
                return None

            # Embed each engram and compute similarities
            similarities = []
            for engram in engrams:
                engram_embed_r = await client.post(
                    f"{LLM_GATEWAY}/embed",
                    json={"model": "auto", "texts": [engram["content"]]},
                )
                if engram_embed_r.status_code != 200:
                    continue
                engram_vec = (engram_embed_r.json().get("embeddings") or [[]])[0]
                if engram_vec:
                    sim = _cosine_similarity(query_vec, engram_vec)
                    similarities.append({"engram_id": engram["id"], "similarity": sim})

            if not similarities:
                return None

            avg_sim = sum(s["similarity"] for s in similarities) / len(similarities)

        return {
            "dimension": "memory_relevance",
            "score": max(0.0, min(1.0, avg_sim)),
            "confidence": min(1.0, len(similarities) / 5.0),
            "metadata": {
                "engram_ids": engram_ids,
                "similarities": similarities,
                "query": query_text[:200],
            },
        }
    except Exception as e:
        log.debug("memory_relevance scoring failed: %s", e)
        return None


def score_memory_recall(user_message: str) -> dict[str, Any] | None:
    """Detect if the user is correcting Nova's memory.

    Only returns a score when a correction IS detected. Absence of a
    row = implicit 1.0 when aggregating.
    """
    for pattern in CORRECTION_PATTERNS:
        match = pattern.search(user_message)
        if match:
            return {
                "dimension": "memory_recall",
                "score": 0.3,
                "confidence": 0.7,
                "metadata": {
                    "matched_pattern": pattern.pattern,
                    "user_message_excerpt": user_message[:200],
                },
            }
    return None


def score_tool_accuracy(agent_output: dict | list | None) -> dict[str, Any] | None:
    """Score tool call accuracy from agent session output.

    Parses conversation messages for tool_use/tool_result blocks.
    Detects errors via known prefixes.
    """
    if not agent_output:
        return None

    ERROR_PREFIXES = (
        "Tool execution blocked:",
        "MCP dispatch error:",
        "Error:",
        "error:",
        "Failed to execute",
        "Tool not found:",
    )

    messages = agent_output if isinstance(agent_output, list) else []
    if isinstance(agent_output, dict):
        messages = agent_output.get("messages", [])

    total_calls = 0
    errored_calls = 0
    tools_called = []
    errors = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        content = msg.get("content", "")

        # Count tool_use blocks
        if role == "assistant" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    total_calls += 1
                    tools_called.append(block.get("name", "unknown"))

        # Check tool_result blocks for errors
        if role == "tool" or (isinstance(content, str) and any(content.startswith(p) for p in ERROR_PREFIXES)):
            if isinstance(content, str) and any(content.startswith(p) for p in ERROR_PREFIXES):
                errored_calls += 1
                errors.append(content[:200])

    if total_calls == 0:
        return None

    score = max(0.0, (total_calls - errored_calls) / total_calls)

    return {
        "dimension": "tool_accuracy",
        "score": score,
        "confidence": min(1.0, total_calls / 3.0),
        "metadata": {
            "tools_called": tools_called,
            "total_calls": total_calls,
            "errored_calls": errored_calls,
            "errors": errors,
        },
    }


async def score_response_coherence(
    query_text: str,
    response_text: str,
    had_tool_calls: bool = False,
) -> dict[str, Any] | None:
    """Score topic coherence between query and response.

    Skips tool-heavy responses to avoid penalizing correct tool use.
    """
    if had_tool_calls:
        return None

    if not query_text.strip() or not response_text.strip():
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            q_r = await client.post(f"{LLM_GATEWAY}/embed", json={"model": "auto", "texts": [query_text]})
            r_r = await client.post(f"{LLM_GATEWAY}/embed", json={"model": "auto", "texts": [response_text[:2000]]})

            if q_r.status_code != 200 or r_r.status_code != 200:
                return None

            q_vec = (q_r.json().get("embeddings") or [[]])[0]
            r_vec = (r_r.json().get("embeddings") or [[]])[0]

            if not q_vec or not r_vec:
                return None

            sim = _cosine_similarity(q_vec, r_vec)

        return {
            "dimension": "response_coherence",
            "score": max(0.0, min(1.0, sim)),
            "confidence": 0.8,
            "metadata": {
                "similarity": sim,
                "query_len": len(query_text),
                "response_len": len(response_text),
            },
        }
    except Exception as e:
        log.debug("response_coherence scoring failed: %s", e)
        return None


async def score_memory_usage(
    engram_ids: list[str],
    response_text: str,
) -> dict[str, Any] | None:
    """Score whether retrieved engrams were actually used in the response.

    Checks if key phrases from engram content appear in the assistant's response.
    High score = memory was useful. Low score = memory was retrieved but ignored.
    No embedding calls needed — pure text matching for speed.
    """
    if not engram_ids or not response_text:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            batch_r = await client.post(
                f"{MEMORY_SERVICE}/api/v1/engrams/batch",
                json={"ids": engram_ids[:10]},  # Cap at 10 to limit cost
            )
            if batch_r.status_code != 200:
                return None
            engrams = batch_r.json()

        if not engrams:
            return None

        response_lower = response_text.lower()
        used = 0
        checked = 0
        used_ids = []

        for engram in engrams:
            content = engram.get("content", "")
            if len(content) < 10:
                continue
            checked += 1

            # Extract key phrases (3+ word sequences) from engram content
            words = content.lower().split()
            # Check 3-grams for presence in response
            found = False
            for i in range(len(words) - 2):
                trigram = " ".join(words[i:i+3])
                if len(trigram) > 8 and trigram in response_lower:
                    found = True
                    break

            if found:
                used += 1
                used_ids.append(engram["id"])

        if checked == 0:
            return None

        score = used / checked

        return {
            "dimension": "memory_usage",
            "score": score,
            "confidence": min(1.0, checked / 5.0),
            "metadata": {
                "engrams_checked": checked,
                "engrams_used": used,
                "used_ids": used_ids,
            },
        }
    except Exception as e:
        log.debug("memory_usage scoring failed: %s", e)
        return None


async def score_task_completion(
    task_status: str,
    task_id: str,
    pool,
) -> dict[str, Any] | None:
    """Score pipeline task completion quality.

    Joins with guardrail_findings to determine finding presence.
    """
    STATUS_SCORES = {
        "complete": 1.0,
        "pending_human_review": 0.4,
        "failed": 0.2,
        "cancelled": 0.1,
    }

    base_score = STATUS_SCORES.get(task_status)
    if base_score is None:
        return None

    has_findings = False
    if task_status == "complete":
        try:
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM guardrail_findings WHERE task_id = $1",
                    task_id,
                )
                has_findings = (count or 0) > 0
        except Exception:
            pass

    score = 0.6 if (task_status == "complete" and has_findings) else base_score

    return {
        "dimension": "task_completion",
        "score": score,
        "confidence": 0.9,
        "metadata": {
            "task_status": task_status,
            "has_guardrail_findings": has_findings,
        },
    }


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
