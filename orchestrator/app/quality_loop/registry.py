"""Loop registry — single source of truth for which loops exist + their agency.

Agency mode (auto_apply | propose_for_approval | alert_only) is loaded
from platform_config at startup and is hot-reloadable via the API.
"""
from __future__ import annotations

import logging

from app.quality_loop.base import QualityLoop

log = logging.getLogger(__name__)

_VALID_AGENCY = {"auto_apply", "propose_for_approval", "alert_only"}


class RegisteredLoop:
    """Wrapper that lets agency be mutated without rebinding the loop instance."""
    def __init__(self, impl: QualityLoop):
        self.impl = impl
        self.agency = impl.agency

    @property
    def name(self) -> str:
        return self.impl.name


class LoopRegistry:
    def __init__(self) -> None:
        self._loops: dict[str, RegisteredLoop] = {}

    def register(self, loop: QualityLoop) -> None:
        if loop.name in self._loops:
            raise ValueError(f"loop '{loop.name}' already registered")
        self._loops[loop.name] = RegisteredLoop(loop)

    def get(self, name: str) -> RegisteredLoop:
        if name not in self._loops:
            raise KeyError(f"no loop named '{name}'")
        return self._loops[name]

    def list(self) -> list[RegisteredLoop]:
        return list(self._loops.values())

    def set_agency(self, name: str, mode: str) -> None:
        if mode not in _VALID_AGENCY:
            raise ValueError(f"invalid agency mode: {mode}")
        self.get(name).agency = mode  # type: ignore[assignment]


# Module-level singleton — populated by app/main.py at startup
_REGISTRY: LoopRegistry | None = None


def get_registry() -> LoopRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = LoopRegistry()
    return _REGISTRY


async def load_agency_from_config(registry: LoopRegistry) -> None:
    """Read platform_config keys quality.loops.{name}.agency and apply."""
    from app.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value FROM platform_config WHERE key LIKE 'quality.loops.%.agency'"
        )
    for row in rows:
        # key format: quality.loops.<loop_name>.agency
        parts = row["key"].split(".")
        if len(parts) != 4:
            continue
        loop_name = parts[2]
        try:
            mode = row["value"] if isinstance(row["value"], str) else row["value"]
            if isinstance(mode, dict):
                continue
            mode_str = mode.strip('"') if isinstance(mode, str) else str(mode)
            registry.set_agency(loop_name, mode_str)
        except (KeyError, ValueError) as e:
            log.warning("could not apply agency for %s: %s", loop_name, e)
