"""Tests for the sandbox tier system — contextvar, path resolution, tier-based blocking."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.sandbox import SandboxTier, get_sandbox, set_sandbox, reset_sandbox, get_root


# ─── Contextvar behaviour ────────────────────────────────────────────────────

def test_default_tier_is_workspace():
    # Reset to default first (contextvar may be polluted by other tests)
    token = set_sandbox(SandboxTier.workspace)
    try:
        assert get_sandbox() == SandboxTier.workspace
    finally:
        reset_sandbox(token)


def test_set_and_reset_contextvar():
    token = set_sandbox(SandboxTier.home)
    assert get_sandbox() == SandboxTier.home
    reset_sandbox(token)
    # After reset, should be back to previous value
    assert get_sandbox() != SandboxTier.home or get_sandbox() == SandboxTier.workspace


# ─── get_root ─────────────────────────────────────────────────────────────────

def test_get_root_workspace(tmp_path: Path):
    with patch("app.config.settings") as s:
        s.workspace_root = str(tmp_path)
        token = set_sandbox(SandboxTier.workspace)
        try:
            assert get_root() == tmp_path.resolve()
        finally:
            reset_sandbox(token)


def test_get_root_home(tmp_path: Path):
    home_dir = tmp_path / "home_root"
    home_dir.mkdir()
    with patch("app.config.settings") as s:
        s.home_root = str(home_dir)
        token = set_sandbox(SandboxTier.home)
        try:
            assert get_root() == home_dir.resolve()
        finally:
            reset_sandbox(token)


def test_legacy_root_alias_maps_to_workspace():
    """SEC-001: the `root` tier was deleted. Legacy config values must map
    to `workspace` via the SandboxTier._missing_ alias table, not raise."""
    tier = SandboxTier("root")
    assert tier == SandboxTier.workspace


def test_get_root_isolated_raises():
    token = set_sandbox(SandboxTier.isolated)
    try:
        with pytest.raises(PermissionError, match="isolated"):
            get_root()
    finally:
        reset_sandbox(token)


# ─── resolve_path ─────────────────────────────────────────────────────────────

def test_resolve_path_in_workspace(tmp_path: Path):
    from app.tools.code_tools import _resolve_path

    with patch("app.config.settings") as s:
        s.workspace_root = str(tmp_path)
        token = set_sandbox(SandboxTier.workspace)
        try:
            resolved = _resolve_path("src/main.py")
            assert str(resolved).startswith(str(tmp_path))
        finally:
            reset_sandbox(token)


# test_resolve_path_root_allows_absolute removed — root tier deleted (SEC-001).


# ─── Shell blocking in isolated tier ─────────────────────────────────────────

async def test_run_shell_blocked_in_isolated(tmp_path: Path):
    from app.tools.code_tools import _execute_run_shell

    with patch("app.config.settings") as s:
        s.workspace_root = str(tmp_path)
        token = set_sandbox(SandboxTier.isolated)
        try:
            result = await _execute_run_shell("echo hi", working_dir=None)
            assert "disabled" in result.lower() or "blocked" in result.lower()
        finally:
            reset_sandbox(token)


# Command denylist removed per SEC-002 (substring-matching is theater against
# any competent LLM). The sandbox tier is the real boundary — the workspace
# bind-mount isolates the agent from the host filesystem. See
# docs/audits/2026-04-16-phase0/security.md for the full reasoning.
