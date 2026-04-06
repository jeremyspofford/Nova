"""API endpoints for AI quality scores and benchmark results."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import httpx

from app.db import get_pool
from app.auth import AdminDep
from app.config import settings

log = logging.getLogger(__name__)
quality_router = APIRouter(tags=["quality"])


class ScoreBucket(BaseModel):
    period: str
    dimension: str
    avg_score: float
    count: int


class QualitySummary(BaseModel):
    period_days: int
    dimensions: dict
    composite: float


@quality_router.get("/api/v1/quality/scores", response_model=list[ScoreBucket])
async def get_quality_scores(
    _admin: AdminDep,
    dimension: str | None = None,
    conversation_id: str | None = None,
    granularity: str = Query("daily", regex="^(hourly|daily)$"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
):
    """Time-bucketed quality scores for dashboard charts."""
    pool = get_pool()

    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(from_) if from_ else now - timedelta(days=7)
    end = datetime.fromisoformat(to) if to else now

    trunc = "hour" if granularity == "hourly" else "day"

    conditions = ["created_at >= $1", "created_at <= $2"]
    params: list = [start, end]
    idx = 3

    if dimension:
        conditions.append(f"dimension = ${idx}")
        params.append(dimension)
        idx += 1

    if conversation_id:
        conditions.append(f"conversation_id = ${idx}::uuid")
        params.append(conversation_id)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                date_trunc('{trunc}', created_at) AS period,
                dimension,
                AVG(score) AS avg_score,
                COUNT(*) AS count
            FROM quality_scores
            WHERE {where}
            GROUP BY period, dimension
            ORDER BY period DESC
            """,
            *params,
        )

    return [
        ScoreBucket(
            period=row["period"].isoformat(),
            dimension=row["dimension"],
            avg_score=round(float(row["avg_score"]), 4),
            count=row["count"],
        )
        for row in rows
    ]


@quality_router.get("/api/v1/quality/summary")
async def get_quality_summary(
    _admin: AdminDep,
    period: str = Query("7d", regex=r"^\d+d$"),
):
    """Aggregated quality averages and trend vs previous period."""
    pool = get_pool()
    days = int(period.rstrip("d"))
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=days)
    prev_start = current_start - timedelta(days=days)

    async with pool.acquire() as conn:
        current_rows = await conn.fetch(
            """
            SELECT dimension, AVG(score) AS avg, COUNT(*) AS count
            FROM quality_scores
            WHERE created_at >= $1
            GROUP BY dimension
            """,
            current_start,
        )

        prev_rows = await conn.fetch(
            """
            SELECT dimension, AVG(score) AS avg
            FROM quality_scores
            WHERE created_at >= $1 AND created_at < $2
            GROUP BY dimension
            """,
            prev_start,
            current_start,
        )

    prev_map = {r["dimension"]: float(r["avg"]) for r in prev_rows}

    WEIGHTS = {
        "memory_relevance": 0.30,
        "memory_recall": 0.25,
        "tool_accuracy": 0.20,
        "response_coherence": 0.15,
        "task_completion": 0.10,
    }

    dimensions = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for row in current_rows:
        dim = row["dimension"]
        avg = round(float(row["avg"]), 4)
        prev_avg = prev_map.get(dim)
        trend = round(avg - prev_avg, 4) if prev_avg is not None else 0.0

        dimensions[dim] = {
            "avg": avg,
            "count": row["count"],
            "trend": trend,
        }

        w = WEIGHTS.get(dim, 0.0)
        weighted_sum += avg * w
        weight_total += w

    composite = round((weighted_sum / weight_total) * 100, 2) if weight_total > 0 else 0.0

    return {
        "period_days": days,
        "dimensions": dimensions,
        "composite": composite,
    }


@quality_router.post("/api/v1/benchmarks/run-quality", status_code=202)
async def run_quality_benchmark(
    _admin: AdminDep,
    category: str | None = None,
):
    """Kick off a quality benchmark run as a background task.

    Seeds test engrams, runs conversations, scores results, and writes
    to quality_benchmark_runs. Returns run_id for tracking.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO quality_benchmark_runs (status, metadata)
            VALUES ('running', $1)
            RETURNING id::text
            """,
            {"category_filter": category},
        )

    # Run benchmark in background
    asyncio.create_task(_run_benchmark_background(run_id, category))

    return {"run_id": run_id, "status": "running"}


async def _run_benchmark_background(run_id: str, category: str | None = None):
    """Execute benchmark cases and post results. Runs as a background task."""
    import uuid as _uuid

    # Use container-internal URLs
    orch_base = "http://localhost:8000"
    memory_base = "http://memory-service:8002"
    admin_headers = {"X-Admin-Secret": settings.nova_admin_secret}

    # Inline benchmark cases (benchmarks package isn't in the container)
    cases = [
        {"name": "simple_preference_recall", "category": "factual_recall", "seed_engrams": [{"content": "The user's favorite programming language is Rust", "source_type": "chat"}], "messages": ["What's my favorite programming language?"], "expect_memory_hit": True},
        {"name": "entity_recall", "category": "factual_recall", "seed_engrams": [{"content": "Nova is deployed on a machine with an AMD RX 7900 XTX GPU", "source_type": "chat"}], "messages": ["What GPU does my Nova machine have?"], "expect_memory_hit": True},
        {"name": "preference_update", "category": "contradiction", "seed_engrams": [{"content": "The user prefers Python for all backend work", "source_type": "chat"}, {"content": "The user has switched to Go for backend services", "source_type": "chat"}], "messages": ["What language do I prefer for backend work?"], "expect_memory_hit": True},
        {"name": "health_check_tool", "category": "tool_selection", "seed_engrams": [], "messages": ["Is the memory service healthy right now?"], "expect_tool_call": "check_service_health"},
        {"name": "unknown_topic", "category": "hallucination", "seed_engrams": [], "messages": ["What's my cat's name?"], "expect_no_hallucination": True},
        {"name": "recent_work_recall", "category": "temporal", "seed_engrams": [{"content": "Last week the user was debugging the cortex thinking loop", "source_type": "chat"}], "messages": ["What was I working on last week?"], "expect_memory_hit": True},
    ]
    if category:
        cases = [c for c in cases if c["category"] == category]

    results = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cases": [],
        "category_scores": {},
    }

    pool = get_pool()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            for case in cases:
                log.info("Benchmark [%s]: running %s", run_id[:8], case["name"])
                tag = str(_uuid.uuid4())[:8]

                # Seed engrams
                engram_ids = []
                for engram in case.get("seed_engrams", []):
                    r = await client.post(
                        f"{memory_base}/api/v1/engrams/ingest",
                        json={
                            "raw_text": f"[benchmark:{tag}] {engram['content']}",
                            "source_type": engram.get("source_type", "chat"),
                        },
                    )
                    if r.status_code == 201:
                        engram_ids.extend(r.json().get("engram_ids", []))
                    await asyncio.sleep(2)

                # Run conversation
                agents_r = await client.get(f"{orch_base}/api/v1/agents", headers=admin_headers)
                agent_id = None
                if agents_r.status_code == 200:
                    agents_list = agents_r.json()
                    if isinstance(agents_list, list):
                        for a in agents_list:
                            if a.get("name", "").lower() in ("chat", "default", "nova"):
                                agent_id = a["id"]
                                break
                        if not agent_id and agents_list:
                            agent_id = agents_list[0].get("id")

                responses = []
                if agent_id:
                    for msg in case.get("messages", []):
                        r = await client.post(
                            f"{orch_base}/api/v1/tasks",
                            json={"agent_id": agent_id, "messages": [{"role": "user", "content": msg}]},
                            headers=admin_headers,
                            timeout=120,
                        )
                        if r.status_code in (200, 201, 202):
                            task_id = r.json().get("task_id", r.json().get("id"))
                            for _ in range(60):
                                sr = await client.get(f"{orch_base}/api/v1/tasks/{task_id}", headers=admin_headers)
                                if sr.status_code == 200:
                                    task = sr.json()
                                    if task.get("status") in ("complete", "failed", "cancelled", "clarification_needed", "pending_human_review"):
                                        responses.append(task)
                                        break
                                await asyncio.sleep(2)

                # Score
                scores = {}
                for resp in responses:
                    output = resp.get("final_output", resp.get("output", ""))
                    if isinstance(output, dict):
                        output = json.dumps(output)
                    output_lower = (output or "").lower()

                    if case.get("expect_memory_hit"):
                        seeded_terms = []
                        for engram in case.get("seed_engrams", []):
                            words = engram["content"].lower().split()
                            seeded_terms.extend([w for w in words if len(w) > 4][:3])
                        hits = sum(1 for t in seeded_terms if t in output_lower)
                        scores["memory_hit"] = min(1.0, hits / max(len(seeded_terms), 1))

                    if case.get("expect_tool_call"):
                        tools = resp.get("metadata", {}).get("tools_used", [])
                        scores["tool_selection"] = 1.0 if case["expect_tool_call"] in tools else 0.0

                    if case.get("expect_no_hallucination"):
                        hedging = any(p in output_lower for p in ["don't know", "don't have", "no information", "not sure", "can't find", "no memory"])
                        scores["no_hallucination"] = 1.0 if hedging else 0.0

                results["cases"].append({
                    "name": case["name"],
                    "category": case["category"],
                    "scores": scores,
                    "composite": sum(scores.values()) / max(len(scores), 1),
                    "seeded_engrams": len(engram_ids),
                    "responses": len(responses),
                })

        # Aggregate
        by_cat: dict[str, list[float]] = {}
        for cr in results["cases"]:
            by_cat.setdefault(cr["category"], []).append(cr["composite"])
        results["category_scores"] = {cat: round(sum(s) / len(s), 4) for cat, s in by_cat.items()}
        all_composites = [cr["composite"] for cr in results["cases"]]
        composite = round((sum(all_composites) / len(all_composites)) * 100, 2) if all_composites else 0.0
        results["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Write results to DB
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE quality_benchmark_runs
                SET status = 'complete',
                    completed_at = NOW(),
                    composite_score = $2,
                    category_scores = $3,
                    case_results = $4
                WHERE id = CAST($1 AS uuid)
                """,
                run_id, composite,
                results["category_scores"],
                results["cases"],
            )
        log.info("Benchmark [%s] complete: %.1f%% composite", run_id[:8], composite)

    except Exception as e:
        log.exception("Benchmark [%s] failed: %s", run_id[:8], e)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE quality_benchmark_runs
                    SET status = 'failed', completed_at = NOW(),
                        metadata = metadata || $2
                    WHERE id = CAST($1 AS uuid)
                    """,
                    run_id, {"error": str(e)},
                )
        except Exception:
            pass


@quality_router.post("/api/v1/benchmarks/quality-results")
async def post_quality_benchmark_results(
    _admin: AdminDep,
    results: dict,
):
    """Receive benchmark results from external runner (make benchmark-quality)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO quality_benchmark_runs
                (status, completed_at, composite_score, category_scores, case_results, metadata)
            VALUES ('completed', NOW(), $1, $2, $3, $4)
            RETURNING id::text
            """,
            results.get("composite_score", 0),
            results.get("category_scores", {}),
            results.get("cases", []),
            {"run_id": results.get("run_id"), "started_at": results.get("started_at")},
        )
    return {"id": run_id, "status": "completed"}


@quality_router.get("/api/v1/benchmarks/quality-results")
async def get_quality_benchmark_results(
    _admin: AdminDep,
    limit: int = Query(10, ge=1, le=50),
):
    """Return recent quality benchmark runs."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, started_at, completed_at, status,
                   composite_score, category_scores, case_results, metadata
            FROM quality_benchmark_runs
            ORDER BY started_at DESC
            LIMIT $1
            """,
            limit,
        )

    return [
        {
            "id": row["id"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "status": row["status"],
            "composite_score": float(row["composite_score"]) if row["composite_score"] else None,
            "category_scores": row["category_scores"] or {},
            "case_results": row["case_results"] or [],
            "metadata": row["metadata"] or {},
        }
        for row in rows
    ]


@quality_router.delete("/api/v1/benchmarks/quality-results")
async def delete_all_benchmark_results(_admin: AdminDep):
    """Delete all benchmark runs and quality scores."""
    pool = get_pool()
    async with pool.acquire() as conn:
        bench_del = await conn.execute("DELETE FROM quality_benchmark_runs")
        score_del = await conn.execute("DELETE FROM quality_scores")
    return {
        "benchmark_runs_deleted": int(bench_del.split()[-1]) if bench_del else 0,
        "quality_scores_deleted": int(score_del.split()[-1]) if score_del else 0,
    }
