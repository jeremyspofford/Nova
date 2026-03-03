"""
Structured JSON logging for all Nova services.

Usage:
    from nova_contracts.logging import configure_logging
    configure_logging("orchestrator", "INFO")

All log lines become single-line JSON with keys:
    timestamp, level, logger, message, service, + any extras from context vars.

Call set_context() from pipeline code to attach task_id/agent_id/session_id
to all subsequent log lines in the same async task.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Context var holding extra fields (task_id, agent_id, session_id, etc.)
_log_context: ContextVar[dict[str, Any]] = ContextVar("nova_log_context", default={})

_service_name: str = "unknown"


def set_context(**kwargs: Any) -> None:
    """Set correlation IDs for the current async task's log lines."""
    current = _log_context.get()
    _log_context.set({**current, **kwargs})


def clear_context() -> None:
    """Reset correlation context (call at end of pipeline stage)."""
    _log_context.set({})


class JSONFormatter(logging.Formatter):
    """Single-line JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": _service_name,
        }

        # Merge async context vars (task_id, agent_id, etc.)
        ctx = _log_context.get()
        if ctx:
            entry.update(ctx)

        # Include exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)


def configure_logging(service: str, level: str = "INFO") -> None:
    """Replace default logging with structured JSON output."""
    global _service_name
    _service_name = service

    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers
    for name in ("uvicorn.access", "httpcore", "httpx", "litellm", "LiteLLM"):
        logging.getLogger(name).setLevel(logging.WARNING)
