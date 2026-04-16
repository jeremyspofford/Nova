"""
Handlers for the two default scheduled triggers: system health + daily summary.

Both return the typed contract:
    {"status": "ok", "message": str}
    {"status": "action_needed", "title": str, "description": str, "details": dict | None}
"""
import logging
import shutil
from datetime import datetime, timedelta, timezone

import psutil
from sqlalchemy.orm import Session

from app import llm_client
from app.models.run import Run
from app.models.task import Task
from app.models.event import Event

log = logging.getLogger(__name__)

DISK_THRESHOLD_PCT = 85
MEMORY_THRESHOLD_PCT = 90
STALE_TASK_HOURS = 24
FAILED_RUN_RATE_THRESHOLD = 0.5


def handle_system_health(input: dict, db: Session) -> dict:
    """Deterministic health check: disk, memory, stale tasks, recent failed runs."""
    total, used, free = shutil.disk_usage("/")
    disk_pct = (used / total) * 100 if total else 0
    if disk_pct > DISK_THRESHOLD_PCT:
        return {
            "status": "action_needed",
            "title": f"Disk at {disk_pct:.0f}% (container `/`)",
            "description": (
                f"Container root disk usage is {disk_pct:.0f}% "
                f"(used {used // (1024**3)}GB of {total // (1024**3)}GB). "
                "Free space or investigate what's filling the volume."
            ),
            "details": {"disk_pct": disk_pct, "used_bytes": used, "total_bytes": total},
        }

    mem_pct = psutil.virtual_memory().percent
    if mem_pct > MEMORY_THRESHOLD_PCT:
        return {
            "status": "action_needed",
            "title": f"Memory at {mem_pct:.0f}%",
            "description": (
                f"System memory at {mem_pct:.0f}% — investigate leaks or resize."
            ),
            "details": {"memory_pct": mem_pct},
        }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_TASK_HOURS)
    stale_count = (
        db.query(Task)
        .filter(Task.status.in_(["pending", "running"]))
        .filter(Task.created_at < cutoff)
        .count()
    )
    if stale_count > 0:
        return {
            "status": "action_needed",
            "title": f"{stale_count} stale task(s)",
            "description": (
                f"{stale_count} task(s) have been pending/running for > "
                f"{STALE_TASK_HOURS}h — review triage pipeline."
            ),
            "details": {"stale_count": stale_count},
        }

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_runs = db.query(Run).filter(Run.started_at >= hour_ago).all()
    if recent_runs:
        failed = sum(1 for r in recent_runs if r.status == "failed")
        rate = failed / len(recent_runs)
        if rate > FAILED_RUN_RATE_THRESHOLD:
            return {
                "status": "action_needed",
                "title": f"{failed}/{len(recent_runs)} recent runs failed",
                "description": (
                    f"{failed} of {len(recent_runs)} runs in the last hour failed "
                    f"({rate:.0%}). Investigate which tool(s) are breaking."
                ),
                "details": {"failed": failed, "total": len(recent_runs)},
            }

    return {
        "status": "ok",
        "message": (
            f"disk {disk_pct:.0f}%, mem {mem_pct:.0f}%, "
            f"{stale_count} stale, "
            f"{sum(1 for r in recent_runs if r.status == 'failed')}/{len(recent_runs)} runs failed 1h"
        ),
    }


def _build_summary_digest(db: Session, hours: int) -> str:
    """Collect last N hours of events, runs, task transitions into a text digest."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    events = db.query(Event).filter(Event.timestamp >= since).order_by(Event.timestamp).all()
    runs = db.query(Run).filter(Run.started_at >= since).order_by(Run.started_at).all()
    tasks_completed = (
        db.query(Task)
        .filter(Task.status.in_(["done", "failed"]))
        .filter(Task.updated_at >= since)
        .order_by(Task.updated_at)
        .all()
    )

    lines = [f"Activity digest for the last {hours} hours:", ""]
    lines.append(f"Events: {len(events)}")
    for e in events[:20]:
        lines.append(f"  - [{e.type}] {e.subject or ''} (source={e.source})")
    if len(events) > 20:
        lines.append(f"  ... {len(events) - 20} more")

    lines.append("")
    lines.append(f"Tool runs: {len(runs)}")
    by_tool: dict[str, dict] = {}
    for r in runs:
        by_tool.setdefault(r.tool_name, {"ok": 0, "failed": 0})
        by_tool[r.tool_name]["ok" if r.status == "succeeded" else "failed"] += 1
    for tool, counts in by_tool.items():
        lines.append(f"  - {tool}: {counts['ok']} ok, {counts['failed']} failed")

    lines.append("")
    lines.append(f"Tasks completed/failed: {len(tasks_completed)}")
    for t in tasks_completed[:20]:
        lines.append(f"  - [{t.status}] {t.title}")
    if len(tasks_completed) > 20:
        lines.append(f"  ... {len(tasks_completed) - 20} more")

    return "\n".join(lines)


def handle_daily_summary(input: dict, db: Session) -> dict:
    """LLM-summarize the last N hours of activity. Always returns ok — the Run record IS the artifact."""
    hours = int(input.get("window_hours", 24))
    digest = _build_summary_digest(db, hours)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system = (
        "You are Nova's daily-digest summarizer. Given a raw activity digest, "
        "produce a 4-8 sentence human-readable summary. Highlight anything unusual "
        "(high failure rate, repeated errors, stalled tasks). Keep it concise."
    )

    try:
        summary = llm_client.route_internal(
            db,
            purpose="summarize_daily",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": digest},
            ],
        )
    except Exception as exc:
        log.warning("daily_summary LLM failed, falling back to raw digest: %s", exc)
        summary = digest

    return {
        "status": "ok",
        "message": f"Daily summary — {today}\n\n{summary}",
    }
