"""Integration tests for the bundled Ollama service.

Verifies that:
1. The ollama service IS in the active stack when local-ollama profile is active.
2. The ollama service IS NOT in the active stack under cloud-only mode (empty profiles).
3. The llm-gateway container can resolve and reach `http://ollama:11434`.
4. A /complete call with `LLM_ROUTING_STRATEGY=local-only` is actually served by
   the bundled Ollama — not silently masked by a cloud fallback.

Tests in this module marked `requires_local_ollama` are skipped under cloud-only
mode by the marker logic in conftest.py. The cloud-only inversion test does NOT
carry that marker — it must run in every mode.
"""
from __future__ import annotations

import os
import subprocess

import httpx
import pytest


@pytest.mark.requires_local_ollama
class TestBundledOllamaCompose:
    """Compose-level checks that the bundled service ships when local-ollama is active."""

    def test_ollama_in_active_services(self):
        """With local-ollama profile active, ollama appears in compose services."""
        result = subprocess.run(
            ["docker", "compose", "config", "--services"],
            capture_output=True, text=True, check=True,
        )
        services = result.stdout.strip().splitlines()
        assert "ollama" in services, (
            f"ollama service is missing under local-ollama profile. "
            f"Got: {services}"
        )

    def test_llm_gateway_depends_on_ollama_health(self):
        """llm-gateway must wait for ollama to be healthy before starting."""
        result = subprocess.run(
            ["docker", "compose", "config", "llm-gateway"],
            capture_output=True, text=True, check=True,
        )
        assert "ollama:" in result.stdout
        # Both redis and ollama should be required-healthy
        assert result.stdout.count("condition: service_healthy") >= 2


class TestCloudOnlyExcludesOllama:
    """Verify that cloud-only mode does NOT pull or start ollama."""

    def test_ollama_excluded_under_empty_profiles(self):
        """COMPOSE_PROFILES='' must not list the ollama service."""
        env = {**os.environ, "COMPOSE_PROFILES": ""}
        result = subprocess.run(
            ["docker", "compose", "config", "--services"],
            capture_output=True, text=True, check=True, env=env,
        )
        services = result.stdout.strip().splitlines()
        assert "ollama" not in services, (
            f"ollama appeared in cloud-only services list: {services}"
        )


@pytest.fixture
def local_only_routing(redis_db1):
    """Pin the gateway to local-only routing for the duration of one test.

    Without this, /complete may silently fall back to a cloud provider when
    Ollama is slow or the model is mid-pull, causing this test to "pass for
    the wrong reason".
    """
    key = "nova:config:llm.routing_strategy"
    prev = redis_db1.get(key)
    redis_db1.set(key, "local-only")
    try:
        yield
    finally:
        if prev is None:
            redis_db1.delete(key)
        else:
            redis_db1.set(key, prev)


@pytest.mark.requires_local_ollama
class TestBundledOllamaReachability:
    """Run-time checks that the gateway can talk to the bundled service."""

    async def test_gateway_resolves_bundled_ollama(self, llm_gateway: httpx.AsyncClient):
        """/health/ready should report ollama as reachable, not 'unreachable'."""
        r = await llm_gateway.get("/health/ready")
        assert r.status_code == 200
        data = r.json()
        ollama_state = data.get("checks", {}).get("ollama", "")
        assert "unreachable" not in ollama_state, (
            f"Gateway cannot reach bundled Ollama: {ollama_state}"
        )

    async def test_gateway_uses_internal_ollama_url(self, llm_gateway: httpx.AsyncClient):
        """The gateway's resolved Ollama URL must NOT be host.docker.internal."""
        r = await llm_gateway.get("/health/ready")
        body = r.json()
        url_hint = str(body.get("checks", {}).get("ollama", ""))
        assert "host.docker.internal" not in url_hint, (
            f"Gateway is still resolving to host.docker.internal — bundled fix incomplete. "
            f"Got: {url_hint}"
        )

    async def test_gateway_complete_actually_served_by_ollama(
        self, llm_gateway: httpx.AsyncClient, local_only_routing
    ):
        """A /complete call under local-only routing must succeed — proving the
        bundled path works end-to-end without cloud fallback."""
        # Pre-pull the model to avoid first-run pull races. Idempotent.
        subprocess.run(
            ["docker", "compose", "exec", "-T", "ollama", "ollama", "pull", "qwen2.5:1.5b"],
            check=False, timeout=600,
        )
        r = await llm_gateway.post(
            "/complete",
            json={
                "model": "qwen2.5:1.5b",
                "messages": [
                    {"role": "user", "content": "Reply with exactly the word: OK"}
                ],
                "max_tokens": 10,
            },
            timeout=300.0,
        )
        assert r.status_code == 200, (
            f"complete returned {r.status_code} under local-only routing — "
            f"bundled Ollama path is broken. Body: {r.text[:300]}"
        )
        body = r.json()
        # Under local-only, success here means Ollama served the call (no fallback was tried).
        assert body.get("content"), "Expected non-empty completion content"
        # Pricing should be zero for local inference (no per-token cost).
        cost = body.get("cost_usd", 0)
        assert cost == 0 or cost == 0.0, (
            f"Non-zero cost ({cost}) under local-only routing suggests a cloud "
            f"provider served this request — bundled Ollama path was bypassed."
        )
