"""
Sandbox tier system — controls filesystem and shell access scope per agent execution.

Tiers:
  workspace — paths scoped to /workspace (default, current behavior)
  nova      — paths scoped to /nova (full repo root)
  host      — no path validation; hard blocks still apply
  isolated  — no filesystem or shell access (Phase 3c, needs Docker-in-Docker)

Usage:
  token = set_sandbox(SandboxTier.nova)
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
    workspace = "workspace"
    nova = "nova"
    host = "host"
    isolated = "isolated"


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
    elif tier == SandboxTier.nova:
        return Path(settings.nova_root).resolve()
    elif tier == SandboxTier.host:
        return Path("/")
    elif tier == SandboxTier.isolated:
        raise PermissionError("Filesystem access disabled in isolated sandbox tier")
    # Fallback (should never happen)
    return Path(settings.workspace_root).resolve()
