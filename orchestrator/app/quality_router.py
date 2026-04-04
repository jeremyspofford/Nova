"""API endpoints for AI quality scores and benchmark results."""
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db import get_pool
from app.auth import AdminDep

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
    """Kick off a quality benchmark run. Returns run_id for tracking.

    Actual benchmark execution happens externally via `make benchmark-quality`.
    This endpoint creates the DB record and marks it as pending.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            """
            INSERT INTO quality_benchmark_runs (status, metadata)
            VALUES ('pending_external', $1)
            RETURNING id::text
            """,
            json.dumps({"category_filter": category, "note": "Run make benchmark-quality from host"}),
        )

    return {"run_id": run_id, "status": "pending_external"}


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
            json.dumps(results.get("category_scores", {})),
            json.dumps(results.get("cases", [])),
            json.dumps({"run_id": results.get("run_id"), "started_at": results.get("started_at")}),
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
