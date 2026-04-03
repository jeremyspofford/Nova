"""
Baseline Markdown Context — a benchmark baseline memory provider.

Loads .md files from a directory, chunks them, embeds via llm-gateway,
and retrieves by cosine similarity. In-memory storage only (no database).
Represents the status quo of CLAUDE.md / project file context injection.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from app.config import settings
from app.routes import chunks, router as memory_router, Chunk, _embed
from app.chunker import chunk_markdown

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


async def _load_markdown_dir(directory: str) -> int:
    """Scan directory for .md files, chunk and embed them into memory."""
    md_dir = Path(directory)
    if not md_dir.is_dir():
        log.warning("Markdown directory does not exist: %s — skipping startup load", directory)
        return 0

    md_files = sorted(md_dir.rglob("*.md"))
    if not md_files:
        log.info("No .md files found in %s", directory)
        return 0

    log.info("Loading %d markdown files from %s", len(md_files), directory)
    total = 0
    for fp in md_files:
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("Failed to read %s: %s", fp, e)
            continue

        rel_path = str(fp.relative_to(md_dir))
        text_chunks = chunk_markdown(text, source_file=rel_path)
        for chunk_text in text_chunks:
            try:
                emb = await _embed(chunk_text)
            except Exception as e:
                log.warning("Failed to embed chunk from %s (skipping): %s", rel_path, e)
                continue

            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                content=chunk_text,
                embedding=emb,
                source_file=rel_path,
                source_type="markdown_file",
            ))
            total += 1

    log.info("Loaded %d chunks from %d files", total, len(md_files))
    return total


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Baseline Markdown Context starting")
    loaded = await _load_markdown_dir(settings.markdown_dir)
    log.info("Startup complete — %d chunks in memory", loaded)
    yield
    log.info("Baseline Markdown Context shutting down")
    chunks.clear()


app = FastAPI(
    title="Baseline Markdown Context",
    version="0.1.0",
    description="Benchmark baseline: markdown chunking + cosine similarity retrieval",
    lifespan=lifespan,
)

# Health endpoints
health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live")
async def liveness():
    return {"status": "alive"}


@health_router.get("/ready")
async def readiness():
    return {
        "status": "ready",
        "chunks_loaded": len(chunks),
    }


app.include_router(health_router)
app.include_router(memory_router)
