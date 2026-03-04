"""E2E tests for git tools — real git repos in temp directories."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.sandbox import SandboxTier, set_sandbox, reset_sandbox

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available in this environment"
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _sandbox_workspace(tmp_path: Path):
    """Point sandbox root at a temp dir and init a git repo."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.workspace_root = str(tmp_path)
        mock_settings.nova_root = str(tmp_path / "_nova")
        mock_settings.shell_timeout_seconds = 30
        token = set_sandbox(SandboxTier.workspace)

        # Init a real git repo
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@nova.dev"],
            cwd=tmp_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, check=True, capture_output=True,
        )

        try:
            yield tmp_path
        finally:
            reset_sandbox(token)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


# ─── Tests ────────────────────────────────────────────────────────────────────

async def test_git_status_clean(repo: Path):
    from app.tools.git_tools import _execute_git_status

    # Make an initial commit so we have a branch
    (repo / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    result = await _execute_git_status(None)
    # Should show branch info but no modified files
    assert "##" in result or "clean" in result.lower()


async def test_git_status_with_changes(repo: Path):
    from app.tools.git_tools import _execute_git_status

    (repo / "new_file.txt").write_text("hello")
    result = await _execute_git_status(None)
    assert "new_file.txt" in result


async def test_git_diff(repo: Path):
    from app.tools.git_tools import _execute_git_diff

    # Create initial commit
    (repo / "file.txt").write_text("line1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True, capture_output=True)

    # Modify the file
    (repo / "file.txt").write_text("line1\nline2\n")
    result = await _execute_git_diff(repo_path=None, file_path=None, staged=False)
    assert "line2" in result


async def test_git_log(repo: Path):
    from app.tools.git_tools import _execute_git_log

    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit one"], cwd=repo, check=True, capture_output=True)

    (repo / "b.txt").write_text("b")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "commit two"], cwd=repo, check=True, capture_output=True)

    result = await _execute_git_log(repo_path=None, n=10)
    assert "commit one" in result
    assert "commit two" in result


async def test_git_commit(repo: Path):
    from app.tools.git_tools import _execute_git_commit

    (repo / "hello.py").write_text("print('hello')\n")
    result = await _execute_git_commit(
        message="add hello script",
        files=["hello.py"],
        repo_path=None,
    )
    assert "add hello script" in result


async def test_full_cycle(repo: Path):
    """status → write → commit → verify in log."""
    from app.tools.git_tools import (
        _execute_git_status,
        _execute_git_commit,
        _execute_git_log,
    )
    from app.tools.code_tools import _execute_write_file

    # Write a file via code tools
    _execute_write_file("app.py", "print('nova')\n")

    # Status should show the new file
    status = await _execute_git_status(None)
    assert "app.py" in status

    # Commit it
    commit_result = await _execute_git_commit(
        message="add app module",
        files=["app.py"],
        repo_path=None,
    )
    assert "add app module" in commit_result

    # Verify in log
    log_result = await _execute_git_log(repo_path=None, n=5)
    assert "add app module" in log_result
