"""Factory reset — selective data wipe with granular preservation options."""

import logging

import asyncpg

from .db import get_pool

logger = logging.getLogger("nova.recovery.factory_reset")

# Tables grouped by data category.
# Order matters — delete from dependent tables first to avoid FK violations.
CATEGORY_TABLES: dict[str, list[str]] = {
    "task_history": [
        "stage_results",
        "tasks",
    ],
    "chat_sessions": [
        "messages",
        "sessions",
    ],
    "pod_config": [
        "pod_agents",
        "pods",
    ],
    "api_keys": [
        "api_keys",
    ],
    "memories": [
        "memories",
    ],
    "usage": [
        "usage_events",
    ],
}

# User-friendly labels for each category
CATEGORY_LABELS: dict[str, str] = {
    "memories":      "Memories (embeddings + semantic store)",
    "api_keys":      "API keys & provider config",
    "task_history":  "Task history & pipeline logs",
    "chat_sessions": "Chat sessions",
    "pod_config":    "Pod & agent configurations",
    "usage":         "Usage tracking data",
}

# What to keep by default (the expensive / personal stuff)
DEFAULT_KEEP = {"memories", "api_keys"}


async def factory_reset(keep: set[str] | None = None) -> dict:
    """
    Wipe selected data categories.

    Args:
        keep: Set of category keys to preserve. Categories NOT in this set get wiped.
              If None, uses DEFAULT_KEEP.
    """
    if keep is None:
        keep = DEFAULT_KEEP

    pool = get_pool()
    wiped: list[str] = []
    kept: list[str] = []
    errors: list[str] = []

    async with pool.acquire() as conn:
        for category, tables in CATEGORY_TABLES.items():
            if category in keep:
                kept.append(category)
                continue

            try:
                async with conn.transaction():
                    for table in tables:
                        # Check if table exists before truncating
                        exists = await conn.fetchval(
                            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                            table,
                        )
                        if exists:
                            await conn.execute(f"TRUNCATE TABLE {table} CASCADE")
                            logger.info("Truncated table: %s", table)
                wiped.append(category)
            except Exception as e:
                logger.warning("Failed to wipe category %s: %s", category, e)
                errors.append(f"{category}: {e}")

    logger.info("Factory reset complete — wiped: %s, kept: %s", wiped, kept)
    return {
        "wiped": wiped,
        "kept": kept,
        "errors": errors if errors else None,
    }


def get_categories() -> list[dict]:
    """Return available categories with labels and defaults."""
    return [
        {
            "key": key,
            "label": CATEGORY_LABELS.get(key, key),
            "default_keep": key in DEFAULT_KEEP,
        }
        for key in CATEGORY_TABLES
    ]
