"""
Sandbox tier system — controls filesystem and shell access scope per agent execution.

Tiers:
  workspace — paths scoped to /workspace (default — bind-mount isolated from host)
  home      — user's home directory on the host (admin-toggle opt-in; see SEC-001)
  isolated  — no filesystem or shell access

Removed 2026-04-17 / SEC-001: the `root` tier (full host filesystem via
/host-root) — the mount + tier together were an RCE-by-design configuration.
Legacy aliases map `root`/`host` to `workspace` to fail safely.

Usage:
  token = set_sandbox(SandboxTier.home)
  try:
      # ... agent execution ...
  finally:
      reset_sandbox(token)
"""
from __future__ import annotations

import contextvars
import enum
from pathlib import Path


class SandboxTier(str, enum.Enum):
    isolated  = "isolated"
    workspace = "workspace"
    home      = "home"

    @classmethod
    def _missing_(cls, value):
        """Backward compat: legacy tiers (`root`, `host`, `nova`) collapse safely.

        `root`/`host` → workspace (SEC-001: tier removed, never enforce host fs).
        `nova` → home (prior rename).
        """
        _ALIASES = {"nova": cls.home, "host": cls.workspace, "root": cls.workspace}
        return _ALIASES.get(value)


_sandbox_var: contextvars.ContextVar[SandboxTier] = contextvars.ContextVar(
    "sandbox_tier", default=SandboxTier.workspace,
)


def set_sandbox(tier: SandboxTier) -> contextvars.Token:
    """Set the sandbox tier for the current execution context. Returns a reset token."""
    return _sandbox_var.set(tier)


def reset_sandbox(token: contextvars.Token) -> None:
    """Reset the sandbox tier to its previous value."""
    _sandbox_var.reset(token)


def get_sandbox() -> SandboxTier:
    """Read the current sandbox tier."""
    return _sandbox_var.get()


def get_root() -> Path:
    """Return the filesystem root for the current sandbox tier.

    Raises PermissionError for the isolated tier.
    """
    from app.config import settings

    tier = get_sandbox()
    if tier == SandboxTier.workspace:
        return Path(settings.workspace_root).resolve()
    elif tier == SandboxTier.home:
        return Path(settings.home_root).resolve()
    elif tier == SandboxTier.isolated:
        raise PermissionError("Filesystem access disabled in isolated sandbox tier")
    return Path(settings.workspace_root).resolve()


# ── Self-modification overlay ────────────────────────────────────────────────

NOVA_SOURCE_ROOT = Path("/nova")

_self_mod_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "self_modification", default=False,
)


def set_self_modification(enabled: bool) -> contextvars.Token:
    """Set whether self-modification is enabled for the current context."""
    return _self_mod_var.set(enabled)


def reset_self_modification(token: contextvars.Token) -> None:
    _self_mod_var.reset(token)


def is_self_modification_enabled() -> bool:
    return _self_mod_var.get()


async def read_self_modification_config() -> bool:
    """Read nova.self_modification from platform_config."""
    try:
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value #>> '{}' AS val FROM platform_config "
                "WHERE key = 'nova.self_modification'"
            )
        return row and row["val"] == "true"
    except Exception:
        return False
