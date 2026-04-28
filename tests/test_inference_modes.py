"""Integration tests for the three NOVA_INFERENCE_MODE settings.

Verifies that setup.sh writes the correct .env values for each mode and that
the resulting docker-compose graph matches expectations. Uses the
--derive-mode-only fast path so tests don't pull models or hit Docker.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_env_var(env_path: Path, key: str) -> str | None:
    """Return the value of KEY in a .env-style file, or None if absent."""
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


@pytest.fixture
def isolated_env(tmp_path):
    """Run setup.sh against a temporary copy of the repo's .env files."""
    env_path = tmp_path / ".env"
    if (REPO_ROOT / ".env.example").exists():
        shutil.copy(REPO_ROOT / ".env.example", env_path)
    return env_path


def _run_derive_mode(env_file: Path, mode: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "NOVA_INFERENCE_MODE": mode, "ENV_FILE": str(env_file)}
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/setup.sh"), "--derive-mode-only"],
        env=env, capture_output=True, text=True, cwd=REPO_ROOT,
    )


@pytest.mark.parametrize("mode,expected_strategy,expects_local_ollama", [
    ("hybrid", "local-first", True),
    ("local-only", "local-only", True),
    ("cloud-only", "cloud-only", False),
])
def test_setup_writes_correct_env(isolated_env, mode, expected_strategy, expects_local_ollama):
    """Each mode must write the correct LLM_ROUTING_STRATEGY and COMPOSE_PROFILES."""
    result = _run_derive_mode(isolated_env, mode)
    assert result.returncode == 0, f"setup.sh failed: stderr={result.stderr[:500]}"

    assert _read_env_var(isolated_env, "NOVA_INFERENCE_MODE") == mode
    assert _read_env_var(isolated_env, "LLM_ROUTING_STRATEGY") == expected_strategy

    profiles = _read_env_var(isolated_env, "COMPOSE_PROFILES") or ""
    profile_set = {p.strip() for p in profiles.split(",") if p.strip()}
    if expects_local_ollama:
        assert "local-ollama" in profile_set, (
            f"local-ollama missing from COMPOSE_PROFILES under {mode!r}: {profiles!r}"
        )
    else:
        assert "local-ollama" not in profile_set, (
            f"local-ollama should not be active under {mode!r}: {profiles!r}"
        )


def test_setup_idempotent(isolated_env):
    """Re-running setup.sh with the same mode must not duplicate keys in .env."""
    for _ in range(3):
        result = _run_derive_mode(isolated_env, "hybrid")
        assert result.returncode == 0, f"setup.sh failed: {result.stderr[:200]}"

    content = isolated_env.read_text()
    for key in ("NOVA_INFERENCE_MODE", "LLM_ROUTING_STRATEGY", "COMPOSE_PROFILES"):
        # Count both line-start positions: at file start, and after a newline.
        count = content.count(f"\n{key}=") + (1 if content.startswith(f"{key}=") else 0)
        assert count == 1, f"{key} appears {count} times after 3 runs; expected 1"


def test_mode_change_preserves_other_profiles(isolated_env):
    """Switching to cloud-only should remove local-ollama but keep unrelated profiles."""
    # Seed the env with multiple profiles
    text = isolated_env.read_text()
    text = "\n".join(
        line for line in text.splitlines() if not line.startswith("COMPOSE_PROFILES=")
    )
    text += "\nCOMPOSE_PROFILES=local-ollama,bridges,knowledge\n"
    isolated_env.write_text(text)

    result = _run_derive_mode(isolated_env, "cloud-only")
    assert result.returncode == 0

    profiles = _read_env_var(isolated_env, "COMPOSE_PROFILES") or ""
    profile_set = {p.strip() for p in profiles.split(",") if p.strip()}
    assert "local-ollama" not in profile_set, (
        f"local-ollama not removed under cloud-only: {profiles!r}"
    )
    assert "bridges" in profile_set, f"bridges was incorrectly stripped: {profiles!r}"
    assert "knowledge" in profile_set, f"knowledge was incorrectly stripped: {profiles!r}"


def test_invalid_mode_rejected(isolated_env):
    """An unknown NOVA_INFERENCE_MODE must abort setup with a clear error."""
    result = _run_derive_mode(isolated_env, "bogus-mode")
    assert result.returncode != 0, "setup.sh accepted invalid mode"
    assert "invalid NOVA_INFERENCE_MODE" in (result.stderr + result.stdout), (
        f"Expected error message not in output. stderr={result.stderr[:300]} stdout={result.stdout[:300]}"
    )
