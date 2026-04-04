"""Benchmark runner: seeds engrams, runs conversations, scores, cleans up.

Usage:
    python -m benchmarks.quality.runner          # run all cases
    python -m benchmarks.quality.runner factual   # run one category
"""
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

import httpx

from benchmarks.quality.cases import BENCHMARK_CASES, BenchmarkCase

log = logging.getLogger(__name__)

ORCH_BASE = "http://localhost:8000"
MEMORY_BASE = "http://localhost:8002"
ADMIN_HEADERS = {"X-Admin-Secret": "nova-admin-secret-change-me"}


async def seed_engrams(
    client: httpx.AsyncClient, case: BenchmarkCase, run_id: str
) -> list[str]:
    """Seed test engrams and return their IDs for cleanup."""
    engram_ids = []
    for engram in case.seed_engrams:
        tagged_content = f"[benchmark:{run_id}] {engram['content']}"
        r = await client.post(
            f"{MEMORY_BASE}/api/v1/engrams/ingest",
            json={
                "raw_text": tagged_content,
                "source_type": engram.get("source_type", "chat"),
            },
        )
        if r.status_code == 201:
            ids = r.json().get("engram_ids", [])
            engram_ids.extend(ids)
        await asyncio.sleep(2)
    return engram_ids


async def run_conversation(
    client: httpx.AsyncClient, messages: list[str]
) -> dict:
    """Send messages through the task API and collect responses."""
    results = {"responses": [], "task_ids": []}

    # Get the default chat agent ID
    agents_r = await client.get(f"{ORCH_BASE}/api/v1/agents", headers=ADMIN_HEADERS)
    agent_id = None
    if agents_r.status_code == 200:
        agents = agents_r.json()
        for a in (agents if isinstance(agents, list) else agents.get("agents", [])):
            if a.get("name", "").lower() in ("chat", "default", "nova"):
                agent_id = a["id"]
                break
        if not agent_id and agents:
            first = agents[0] if isinstance(agents, list) else (agents.get("agents", []) or [{}])[0]
            agent_id = first.get("id")

    if not agent_id:
        log.error("No agent found for benchmark conversations")
        return results

    for msg in messages:
        r = await client.post(
            f"{ORCH_BASE}/api/v1/tasks",
            json={
                "agent_id": agent_id,
                "messages": [{"role": "user", "content": msg}],
            },
            headers=ADMIN_HEADERS,
            timeout=120,
        )
        if r.status_code in (200, 201, 202):
            data = r.json()
            task_id = data.get("task_id", data.get("id"))
            results["task_ids"].append(task_id)

            for _ in range(60):
                status_r = await client.get(
                    f"{ORCH_BASE}/api/v1/tasks/{task_id}",
                    headers=ADMIN_HEADERS,
                )
                if status_r.status_code == 200:
                    task = status_r.json()
                    if task.get("status") in ("complete", "failed", "cancelled"):
                        results["responses"].append(task)
                        break
                await asyncio.sleep(2)

    return results


def score_case(case: BenchmarkCase, results: dict) -> dict:
    """Score a benchmark case against expected behaviors."""
    scores = {}

    for resp in results.get("responses", []):
        output = resp.get("final_output", resp.get("output", ""))
        if isinstance(output, dict):
            output = json.dumps(output)
        output_lower = (output or "").lower()

        if case.expect_memory_hit:
            seeded_terms = []
            for engram in case.seed_engrams:
                words = engram["content"].lower().split()
                key_words = [w for w in words if len(w) > 4]
                seeded_terms.extend(key_words[:3])
            hits = sum(1 for term in seeded_terms if term in output_lower)
            scores["memory_hit"] = min(1.0, hits / max(len(seeded_terms), 1))

        if case.expect_tool_call:
            tools = resp.get("metadata", {}).get("tools_used", [])
            scores["tool_selection"] = 1.0 if case.expect_tool_call in tools else 0.0

        if case.expect_no_hallucination:
            hedging = any(phrase in output_lower for phrase in [
                "don't know", "don't have", "no information",
                "not sure", "can't find", "no memory", "no record",
            ])
            scores["no_hallucination"] = 1.0 if hedging else 0.0

    return scores


async def cleanup_engrams(client: httpx.AsyncClient, run_id: str):
    """Delete engrams tagged with this benchmark run ID."""
    try:
        r = await client.post(
            f"{MEMORY_BASE}/api/v1/engrams/activate",
            json={"query": f"benchmark:{run_id}", "limit": 100},
        )
        if r.status_code == 200:
            engrams = r.json().get("engrams", [])
            for e in engrams:
                if f"benchmark:{run_id}" in e.get("content", ""):
                    await client.delete(
                        f"{MEMORY_BASE}/api/v1/engrams/{e['id']}",
                    )
    except Exception as e:
        log.warning("Benchmark cleanup failed: %s", e)


async def run_benchmarks(category_filter: str | None = None) -> dict:
    """Run all benchmark cases and return aggregate results."""
    run_id = str(uuid.uuid4())[:8]
    cases = BENCHMARK_CASES
    if category_filter:
        cases = [c for c in cases if c.category == category_filter]

    results = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
        "category_scores": {},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for case in cases:
            log.info("Running benchmark: %s", case.name)

            engram_ids = await seed_engrams(client, case, run_id)
            conv_results = await run_conversation(client, case.messages)
            scores = score_case(case, conv_results)

            case_result = {
                "name": case.name,
                "category": case.category,
                "scores": scores,
                "composite": sum(scores.values()) / max(len(scores), 1),
                "seeded_engrams": len(engram_ids),
                "responses": len(conv_results.get("responses", [])),
            }
            results["cases"].append(case_result)
            await cleanup_engrams(client, run_id)

        by_cat: dict[str, list[float]] = {}
        for cr in results["cases"]:
            by_cat.setdefault(cr["category"], []).append(cr["composite"])

        results["category_scores"] = {
            cat: round(sum(scores) / len(scores), 4)
            for cat, scores in by_cat.items()
        }

        all_composites = [cr["composite"] for cr in results["cases"]]
        results["composite_score"] = round(
            (sum(all_composites) / len(all_composites)) * 100, 2
        ) if all_composites else 0.0

        results["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Post results to orchestrator
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{ORCH_BASE}/api/v1/benchmarks/quality-results",
                json=results,
                headers=ADMIN_HEADERS,
            )
    except Exception as e:
        log.warning("Failed to write benchmark results to DB: %s", e)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    category = sys.argv[1] if len(sys.argv) > 1 else None
    result = asyncio.run(run_benchmarks(category))
    print(json.dumps(result, indent=2))
