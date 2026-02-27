"""
Database connection pool and session management.
Uses asyncpg via SQLAlchemy async engine for connection pooling.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

log = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # detect stale connections
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_db():
    """Async context manager providing a database session with auto-commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def run_schema_migrations() -> None:
    """Execute schema.sql on startup. Idempotent — uses IF NOT EXISTS throughout."""
    import re
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    # Strip single-line comments BEFORE splitting on ';' to avoid false splits
    # when a comment contains a semicolon (e.g. "-- note; see also X").
    sql_stripped = re.sub(r"--[^\n]*", "", sql)
    async with engine.begin() as conn:
        for statement in sql_stripped.split(";"):
            stmt = statement.strip()
            if stmt:
                await conn.exec_driver_sql(stmt)
    log.info("Schema migrations applied")
