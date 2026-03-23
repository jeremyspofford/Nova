"""Friction log — CRUD endpoints, stats, and 'Fix This' action.

Endpoints:
  POST   /api/v1/friction          — create entry
  GET    /api/v1/friction          — list (with filters + pagination)
  GET    /api/v1/friction/stats    — aggregate counts for Sprint Health
  GET    /api/v1/friction/:id      — detail
  PATCH  /api/v1/friction/:id      — update status/severity
  DELETE /api/v1/friction/:id      — delete entry + screenshot files
  POST   /api/v1/friction/:id/fix  — create pipeline task from entry
  GET    /api/v1/friction/:id/screenshot — serve screenshot file
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import AdminDep
from app.db import get_pool

log = logging.getLogger(__name__)
router = APIRouter()

# Screenshot storage — Docker volume mount
SCREENSHOT_DIR = Path("/data/friction-screenshots")


# ── Request/Response models ──────────────────────────────────────────────────

class CreateFrictionEntry(BaseModel):
    description: str = Field(..., min_length=1)
    severity: str = Field(default="annoyance")
    screenshot: str | None = None       # base64-encoded full image
    screenshot_thumb: str | None = None  # base64-encoded thumbnail

class UpdateFrictionEntry(BaseModel):
    status: str | None = None
    severity: str | None = None


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.post("/api/v1/friction", status_code=201)
async def create_friction_entry(req: CreateFrictionEntry, _admin: AdminDep):
    """Create a friction log entry."""
    _validate_severity(req.severity)

    pool = get_pool()
    entry_id = str(uuid.uuid4())

    # Handle screenshot files
    screenshot_path = None
    thumb_path = None
    if req.screenshot:
        screenshot_path, thumb_path = _save_screenshots(
            entry_id, req.screenshot, req.screenshot_thumb
        )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO friction_log (id, description, severity, screenshot_path, screenshot_thumb_path)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            entry_id, req.description, req.severity, screenshot_path, thumb_path,
        )
    return _row_to_dict(row)


@router.get("/api/v1/friction")
async def list_friction_entries(
    _admin: AdminDep,
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List friction entries with optional filters and pagination."""
    pool = get_pool()
    conditions = []
    params: list = []
    idx = 1

    if severity:
        conditions.append(f"severity = ${idx}")
        params.append(severity)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if source:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, description, severity, status, source, task_id, user_id,
                   screenshot_path IS NOT NULL AS has_screenshot,
                   metadata, created_at, updated_at
            FROM friction_log
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
    return [_list_row_to_dict(r) for r in rows]


@router.get("/api/v1/friction/stats")
async def friction_stats(_admin: AdminDep):
    """Aggregate friction counts for Sprint Health."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'open') AS open_count,
                COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
                COUNT(*) FILTER (WHERE status = 'fixed') AS fixed_count,
                COUNT(*) AS total_count,
                COUNT(*) FILTER (WHERE severity = 'blocker') AS blocker_count
            FROM friction_log
            """
        )
    return dict(row)


@router.get("/api/v1/friction/{entry_id}")
async def get_friction_entry(entry_id: str, _admin: AdminDep):
    """Get a single friction entry with full details."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM friction_log WHERE id = $1", entry_id
        )
    if not row:
        raise HTTPException(404, "Friction entry not found")
    return _row_to_dict(row)


@router.patch("/api/v1/friction/{entry_id}")
async def update_friction_entry(entry_id: str, req: UpdateFrictionEntry, _admin: AdminDep):
    """Update a friction entry's status or severity."""
    updates = []
    params: list = []
    idx = 1

    if req.status is not None:
        if req.status not in ("open", "in_progress", "fixed"):
            raise HTTPException(422, f"Invalid status: {req.status}")
        updates.append(f"status = ${idx}")
        params.append(req.status)
        idx += 1
    if req.severity is not None:
        _validate_severity(req.severity)
        updates.append(f"severity = ${idx}")
        params.append(req.severity)
        idx += 1

    if not updates:
        raise HTTPException(422, "No fields to update")

    updates.append("updated_at = now()")
    params.append(entry_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE friction_log
            SET {', '.join(updates)}
            WHERE id = ${idx}
            RETURNING *
            """,
            *params,
        )
    if not row:
        raise HTTPException(404, "Friction entry not found")
    return _row_to_dict(row)


@router.delete("/api/v1/friction")
async def bulk_delete_friction_entries(_admin: AdminDep):
    """Delete all friction log entries and their screenshot files."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "DELETE FROM friction_log RETURNING screenshot_path, screenshot_thumb_path"
        )
    # Clean up screenshot files
    for row in rows:
        for path_col in ("screenshot_path", "screenshot_thumb_path"):
            if row[path_col]:
                try:
                    Path(row[path_col]).unlink(missing_ok=True)
                except Exception:
                    pass
    return {"deleted": len(rows)}


@router.delete("/api/v1/friction/{entry_id}", status_code=204)
async def delete_friction_entry(entry_id: str, _admin: AdminDep):
    """Delete a friction entry and its screenshot files."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM friction_log WHERE id = $1 RETURNING screenshot_path, screenshot_thumb_path",
            entry_id,
        )
    if not row:
        raise HTTPException(404, "Friction entry not found")

    # Clean up screenshot files
    for path_col in ("screenshot_path", "screenshot_thumb_path"):
        if row[path_col]:
            try:
                Path(row[path_col]).unlink(missing_ok=True)
            except Exception as e:
                log.warning(f"Screenshot cleanup failed for {row[path_col]}: {e}")


# ── Fix This ─────────────────────────────────────────────────────────────────

@router.post("/api/v1/friction/{entry_id}/fix", status_code=201)
async def fix_friction_entry(entry_id: str, _admin: AdminDep):
    """Create a pipeline task from a friction entry ('Fix This' action)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        entry = await conn.fetchrow(
            "SELECT * FROM friction_log WHERE id = $1", entry_id
        )
    if not entry:
        raise HTTPException(404, "Friction entry not found")

    if entry["status"] == "fixed":
        raise HTTPException(422, "Entry is already fixed")
    if entry["task_id"]:
        raise HTTPException(422, "A fix task already exists for this entry")

    # Create pipeline task
    task_id = str(uuid.uuid4())
    task_input = f"Fix this friction issue: {entry['description']}"

    async with pool.acquire() as conn:
        # Find default pod
        pod = await conn.fetchrow(
            "SELECT id FROM pods WHERE is_system_default = true LIMIT 1"
        )
        pod_id = str(pod["id"]) if pod else None

        await conn.execute(
            """
            INSERT INTO tasks (id, user_input, pod_id, status, metadata, queued_at)
            VALUES ($1, $2, $3::uuid, 'queued', $4::jsonb, now())
            """,
            task_id, task_input, pod_id,
            json.dumps({"source": "friction_log", "friction_id": entry_id}),
        )

        # Update friction entry with task reference
        await conn.execute(
            """
            UPDATE friction_log
            SET task_id = $1, status = 'in_progress', updated_at = now()
            WHERE id = $2
            """,
            task_id, entry_id,
        )

    # Enqueue task
    try:
        from app.queue import enqueue_task
        await enqueue_task(task_id)
    except Exception as e:
        log.warning(f"Task enqueue failed for friction fix: {e}")

    return {"task_id": task_id, "friction_id": entry_id}


# ── Screenshot serving ───────────────────────────────────────────────────────

@router.get("/api/v1/friction/{entry_id}/screenshot")
async def get_friction_screenshot(
    entry_id: str,
    _admin: AdminDep,
    thumb: bool = Query(default=False),
):
    """Serve a friction entry's screenshot file. Requires admin auth."""
    pool = get_pool()
    col = "screenshot_thumb_path" if thumb else "screenshot_path"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {col} FROM friction_log WHERE id = $1", entry_id
        )
    if not row or not row[col]:
        raise HTTPException(404, "Screenshot not found")

    path = Path(row[col])
    if not path.exists():
        raise HTTPException(404, "Screenshot file missing")

    return FileResponse(path, media_type="image/jpeg")


# ── Helpers ──────────────────────────────────────────────────────────────────

VALID_SEVERITIES = {"blocker", "annoyance", "idea"}

def _validate_severity(severity: str) -> None:
    if severity not in VALID_SEVERITIES:
        raise HTTPException(422, f"Invalid severity: {severity}. Must be one of: {VALID_SEVERITIES}")


def _save_screenshots(entry_id: str, full_b64: str, thumb_b64: str | None) -> tuple[str, str | None]:
    """Decode base64 screenshots and save to Docker volume. Returns (full_path, thumb_path)."""
    import base64

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    full_path = SCREENSHOT_DIR / f"{entry_id}_full.jpg"
    try:
        # Strip data URI prefix if present
        if "," in full_b64:
            full_b64 = full_b64.split(",", 1)[1]
        full_path.write_bytes(base64.b64decode(full_b64))
    except Exception as e:
        log.warning(f"Screenshot save failed for {entry_id}: {e}")
        return None, None

    thumb_path_str = None
    if thumb_b64:
        thumb_path = SCREENSHOT_DIR / f"{entry_id}_thumb.jpg"
        try:
            if "," in thumb_b64:
                thumb_b64 = thumb_b64.split(",", 1)[1]
            thumb_path.write_bytes(base64.b64decode(thumb_b64))
            thumb_path_str = str(thumb_path)
        except Exception as e:
            log.warning(f"Thumbnail save failed for {entry_id}: {e}")

    return str(full_path), thumb_path_str


def _row_to_dict(row) -> dict:
    """Convert a DB row to a dict with ISO timestamps."""
    d = dict(row)
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    d["has_screenshot"] = bool(d.get("screenshot_path"))
    # Convert UUID fields to strings
    for k in ("id", "task_id", "user_id"):
        if d.get(k):
            d[k] = str(d[k])
    return d


def _list_row_to_dict(row) -> dict:
    """Convert a list-view DB row (no screenshot paths) to a dict."""
    d = dict(row)
    for k in ("created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    for k in ("id", "task_id", "user_id"):
        if d.get(k):
            d[k] = str(d[k])
    return d
