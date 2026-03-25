"""Intel feed CRUD and content ingestion endpoints."""
from __future__ import annotations

import ipaddress
import json
import logging
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.auth import AdminDep, UserDep
from app.db import get_pool

log = logging.getLogger(__name__)

intel_router = APIRouter(tags=["intel"])


# ── SSRF validation ──────────────────────────────────────────────────────────

BLOCKED_HOSTS = {
    "localhost", "0.0.0.0", "redis", "postgres", "orchestrator", "memory-service",
    "llm-gateway", "cortex", "recovery", "chat-api", "chat-bridge",
    "dashboard", "intel-worker", "metadata.google.internal",
    "host.docker.internal",
}


def _validate_feed_url(url: str) -> str | None:
    """Return error message if URL is unsafe, None if OK."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Scheme '{parsed.scheme}' not allowed"
    hostname = parsed.hostname or ""
    if hostname.lower() in BLOCKED_HOSTS:
        return f"Host '{hostname}' is blocked"
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return f"Private/loopback/link-local IP '{ip}' not allowed"
    except ValueError:
        pass
    return None


# ── Request / Response models ────────────────────────────────────────────────

class CreateFeedRequest(BaseModel):
    name: str
    url: str
    feed_type: str
    category: str | None = None
    check_interval_seconds: int = 3600


class UpdateFeedRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    check_interval_seconds: int | None = None
    enabled: bool | None = None


class FeedStatusUpdate(BaseModel):
    last_checked_at: str
    error_count: int
    last_hash: str | None = None


class ContentItem(BaseModel):
    feed_id: UUID
    content_hash: str
    title: str | None = None
    url: str | None = None
    body: str | None = None
    author: str | None = None
    score: int | None = None
    published_at: str | None = None
    metadata: dict = {}


class IngestContentRequest(BaseModel):
    items: list[ContentItem]


# ── Endpoints ────────────────────────────────────────────────────────────────

@intel_router.get("/api/v1/intel/feeds")
async def list_feeds(
    _user: UserDep,
    enabled: bool | None = Query(default=None),
    category: str | None = Query(default=None),
):
    """List all intel feeds, optionally filtered by enabled status or category."""
    pool = get_pool()
    conditions: list[str] = []
    values: list = []
    idx = 1

    if enabled is not None:
        conditions.append(f"enabled = ${idx}")
        values.append(enabled)
        idx += 1
    if category is not None:
        conditions.append(f"category = ${idx}")
        values.append(category)
        idx += 1

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM intel_feeds{where} ORDER BY created_at DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *values)
    return [dict(r) for r in rows]


@intel_router.post("/api/v1/intel/feeds", status_code=201)
async def create_feed(req: CreateFeedRequest, _user: UserDep):
    """Create a new intel feed. Validates URL for SSRF."""
    error = _validate_feed_url(req.url)
    if error:
        raise HTTPException(status_code=400, detail=f"Invalid feed URL: {error}")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO intel_feeds (name, url, feed_type, category, check_interval_seconds)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            req.name, req.url, req.feed_type, req.category, req.check_interval_seconds,
        )
    log.info("Intel feed created: %s — %s", row["id"], req.name)
    return dict(row)


@intel_router.patch("/api/v1/intel/feeds/{feed_id}")
async def update_feed(feed_id: UUID, req: UpdateFeedRequest, _user: UserDep):
    """Update feed config (name, category, check_interval_seconds, enabled)."""
    updates = req.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_parts = []
    values = []
    for i, (key, val) in enumerate(updates.items(), start=1):
        set_parts.append(f"{key} = ${i}")
        values.append(val)

    values.append(feed_id)
    set_clause = ", ".join(set_parts)
    idx = len(values)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE intel_feeds SET {set_clause}, updated_at = NOW() WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Feed not found")
    log.info("Intel feed updated: %s", feed_id)
    return dict(row)


@intel_router.delete("/api/v1/intel/feeds/{feed_id}", status_code=204)
async def delete_feed(feed_id: UUID, _user: UserDep):
    """Delete an intel feed."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM intel_feeds WHERE id = $1", feed_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Feed not found")
    log.info("Intel feed deleted: %s", feed_id)


@intel_router.patch("/api/v1/intel/feeds/{feed_id}/status")
async def update_feed_status(feed_id: UUID, req: FeedStatusUpdate, _admin: AdminDep):
    """Update feed check status (used by intel-worker)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE intel_feeds
            SET last_checked_at = $1::timestamptz,
                error_count = $2,
                last_hash = $3,
                updated_at = NOW()
            WHERE id = $4
            RETURNING *
            """,
            req.last_checked_at, req.error_count, req.last_hash, feed_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Feed not found")
    log.info("Intel feed status updated: %s", feed_id)
    return dict(row)


@intel_router.post("/api/v1/intel/content")
async def ingest_content(req: IngestContentRequest, _admin: AdminDep):
    """Store new content items. Dedup by content_hash. Returns only newly stored items."""
    pool = get_pool()
    inserted = []
    async with pool.acquire() as conn:
        for item in req.items:
            row = await conn.fetchrow(
                """
                INSERT INTO intel_content_items
                    (feed_id, content_hash, title, url, body, author, score, published_at, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                ON CONFLICT (content_hash) DO NOTHING
                RETURNING id, feed_id, content_hash, title, url
                """,
                item.feed_id, item.content_hash, item.title, item.url,
                item.body, item.author, item.score, item.published_at,
                json.dumps(item.metadata),
            )
            if row:
                inserted.append(dict(row))
    log.info("Intel content ingested: %d new / %d total", len(inserted), len(req.items))
    return inserted


@intel_router.get("/api/v1/intel/stats")
async def intel_stats(_user: UserDep):
    """Aggregate intel stats for the dashboard."""
    pool = get_pool()
    async with pool.acquire() as conn:
        items_this_week = await conn.fetchval(
            "SELECT COUNT(*) FROM intel_content_items WHERE ingested_at > now() - interval '7 days'"
        )
        active_feeds = await conn.fetchval(
            "SELECT COUNT(*) FROM intel_feeds WHERE enabled = true"
        )
        grade_rows = await conn.fetch(
            "SELECT grade, COUNT(*) AS count FROM intel_recommendations GROUP BY grade"
        )
        total_recommendations = await conn.fetchval(
            "SELECT COUNT(*) FROM intel_recommendations"
        )

    grade_map = {r["grade"]: r["count"] for r in grade_rows}
    return {
        "items_this_week": items_this_week or 0,
        "active_feeds": active_feeds or 0,
        "grade_a": grade_map.get("A", 0),
        "grade_b": grade_map.get("B", 0),
        "grade_c": grade_map.get("C", 0),
        "total_recommendations": total_recommendations or 0,
    }
