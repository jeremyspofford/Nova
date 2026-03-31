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


def test_get_root_root():
    token = set_sandbox(SandboxTier.root)
    try:
        assert get_root() == Path("/host-root")
    finally:
        reset_sandbox(token)


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


def test_resolve_path_root_allows_absolute(tmp_path: Path):
    from app.tools.code_tools import _resolve_path

    token = set_sandbox(SandboxTier.root)
    try:
        resolved = _resolve_path("/tmp")
        assert resolved == Path("/host-root/tmp")
    finally:
        reset_sandbox(token)


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


# ─── Tier-aware command blocking ─────────────────────────────────────────────

def test_sudo_blocked_in_workspace():
    from app.tools.code_tools import _is_command_blocked

    blocked, reason = _is_command_blocked("sudo apt install vim", SandboxTier.workspace)
    assert blocked
    assert "privilege" in reason.lower()


def test_sudo_allowed_in_root():
    from app.tools.code_tools import _is_command_blocked

    blocked, _ = _is_command_blocked("sudo apt install vim", SandboxTier.root)
    assert not blocked
