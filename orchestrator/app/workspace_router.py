"""Read-only workspace file access for the dashboard File Viewer."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .config import settings

log = logging.getLogger(__name__)
workspace_router = APIRouter(tags=["workspace"])

MAX_FILE_SIZE = 1_000_000  # 1MB


@workspace_router.get("/api/v1/workspace/files")
async def read_workspace_file(path: str = Query(..., description="Relative path within workspace")):
    """Read a file from the Nova workspace. Read-only, path-traversal safe."""
    workspace = Path(settings.workspace_root).resolve()
    resolved = (workspace / path).resolve()

    # Path traversal prevention
    if not str(resolved).startswith(str(workspace)):
        raise HTTPException(403, "Path traversal blocked")
    if not resolved.is_file():
        raise HTTPException(404, "File not found")

    size = resolved.stat().st_size
    modified_at = datetime.fromtimestamp(resolved.stat().st_mtime, tz=timezone.utc).isoformat()

    if size > MAX_FILE_SIZE:
        return {
            "path": path,
            "content": None,
            "size_bytes": size,
            "modified_at": modified_at,
            "truncated": True,
            "error": f"File too large to display ({size:,} bytes, limit {MAX_FILE_SIZE:,})",
        }

    content = resolved.read_text(errors="replace")
    return {
        "path": path,
        "content": content,
        "size_bytes": size,
        "modified_at": modified_at,
    }
