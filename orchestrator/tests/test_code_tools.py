"""E2E tests for code tools — filesystem and shell operations against real temp dirs."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.sandbox import SandboxTier, set_sandbox, reset_sandbox


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _sandbox_workspace(tmp_path: Path):
    """Point sandbox root at a temp dir for every test."""
    with patch("app.config.settings") as mock_settings:
        mock_settings.workspace_root = str(tmp_path)
        mock_settings.nova_root = str(tmp_path / "_nova")
        mock_settings.shell_timeout_seconds = 30
        token = set_sandbox(SandboxTier.workspace)
        try:
            yield tmp_path
        finally:
            reset_sandbox(token)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


# ─── list_dir ─────────────────────────────────────────────────────────────────

def test_list_dir_root(workspace: Path):
    from app.tools.code_tools import _execute_list_dir

    (workspace / "hello.txt").write_text("hi")
    (workspace / "subdir").mkdir()

    result = _execute_list_dir(".", recursive=False)
    assert "hello.txt" in result
    assert "subdir" in result


def test_list_dir_recursive(workspace: Path):
    from app.tools.code_tools import _execute_list_dir

    (workspace / "a").mkdir()
    (workspace / "a" / "deep.py").write_text("pass")

    result = _execute_list_dir(".", recursive=True)
    assert "deep.py" in result


def test_list_dir_nonexistent():
    from app.tools.code_tools import _execute_list_dir

    result = _execute_list_dir("does_not_exist", recursive=False)
    assert "does not exist" in result


# ─── read_file ────────────────────────────────────────────────────────────────

def test_read_file(workspace: Path):
    from app.tools.code_tools import _execute_read_file

    (workspace / "data.txt").write_text("hello world")
    result = _execute_read_file("data.txt")
    assert "hello world" in result


def test_read_file_truncation(workspace: Path):
    from app.tools.code_tools import _execute_read_file

    (workspace / "big.txt").write_text("x" * 10000)
    result = _execute_read_file("big.txt")
    assert "truncated" in result


def test_read_file_nonexistent():
    from app.tools.code_tools import _execute_read_file

    result = _execute_read_file("nope.txt")
    assert "does not exist" in result


# ─── write_file ───────────────────────────────────────────────────────────────

def test_write_file_creates(workspace: Path):
    from app.tools.code_tools import _execute_write_file

    result = _execute_write_file("new.txt", "content here")
    assert "Created" in result
    assert (workspace / "new.txt").read_text() == "content here"


def test_write_file_overwrites(workspace: Path):
    from app.tools.code_tools import _execute_write_file

    (workspace / "existing.txt").write_text("old")
    result = _execute_write_file("existing.txt", "new")
    assert "Updated" in result
    assert (workspace / "existing.txt").read_text() == "new"


def test_write_file_creates_parents(workspace: Path):
    from app.tools.code_tools import _execute_write_file

    result = _execute_write_file("a/b/c/deep.txt", "nested")
    assert "Created" in result
    assert (workspace / "a" / "b" / "c" / "deep.txt").read_text() == "nested"


# ─── run_shell ────────────────────────────────────────────────────────────────

async def test_run_shell_stdout(workspace: Path):
    from app.tools.code_tools import _execute_run_shell

    result = await _execute_run_shell("echo hello", working_dir=None)
    assert "hello" in result
    assert "exit code: 0" in result


async def test_run_shell_exit_code(workspace: Path):
    from app.tools.code_tools import _execute_run_shell

    result = await _execute_run_shell("false", working_dir=None)
    assert "exit code: 1" in result


async def test_run_shell_timeout(workspace: Path):
    from app.tools.code_tools import _execute_run_shell

    with patch("app.config.settings") as s:
        s.shell_timeout_seconds = 1
        s.workspace_root = str(workspace)
        result = await _execute_run_shell("sleep 10", working_dir=None)
    assert "timed out" in result


# ─── search_codebase ─────────────────────────────────────────────────────────

async def test_search_codebase(workspace: Path):
    from app.tools.code_tools import _execute_search_codebase

    (workspace / "foo.py").write_text("def hello_world():\n    pass\n")
    (workspace / "bar.py").write_text("# nothing here\n")

    result = await _execute_search_codebase(
        pattern="hello_world", path=".", file_glob=None, case_sensitive=False,
    )
    # Should find the match (either via rg or fallback python search)
    assert "hello_world" in result


# ─── Security ─────────────────────────────────────────────────────────────────

def test_path_traversal_rejected():
    from app.tools.code_tools import _resolve_path

    with pytest.raises(ValueError, match="outside sandbox root"):
        _resolve_path("../../etc/passwd")


async def test_command_denylist_sudo():
    from app.tools.code_tools import _execute_run_shell

    result = await _execute_run_shell("sudo ls", working_dir=None)
    assert "blocked" in result.lower()


async def test_command_denylist_rm_rf_root():
    from app.tools.code_tools import _execute_run_shell

    result = await _execute_run_shell("rm -rf /", working_dir=None)
    assert "blocked" in result.lower()
