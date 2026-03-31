"""
Sandbox tier system — controls filesystem and shell access scope per agent execution.

Tiers:
  workspace — paths scoped to /workspace (default)
  home      — paths scoped to user's home directory on the host
  root      — full host filesystem via /host-root mount
  isolated  — no filesystem or shell access

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
    root      = "root"

    @classmethod
    def _missing_(cls, value):
        """Backward compat: accept old tier names during transition."""
        _ALIASES = {"nova": cls.home, "host": cls.root}
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
    elif tier == SandboxTier.root:
        return Path("/host-root")
    elif tier == SandboxTier.isolated:
        raise PermissionError("Filesystem access disabled in isolated sandbox tier")
    return Path(settings.workspace_root).resolve()
