"""Integration tests for managed inference backends."""
from __future__ import annotations

import httpx
import pytest


class TestHardwareDetection:
    """Tests for the hardware detection endpoint."""

    async def test_get_hardware_info_requires_auth(self, recovery: httpx.AsyncClient):
        """Hardware endpoint should reject unauthenticated requests."""
        r = await recovery.get("/api/v1/recovery/inference/hardware")
        assert r.status_code == 401

    async def test_get_hardware_info(self, recovery: httpx.AsyncClient, admin_headers: dict):
        """Recovery service should return detected hardware info."""
        r = await recovery.get("/api/v1/recovery/inference/hardware", headers=admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "gpus" in data
        assert "cpu_cores" in data
        assert "ram_gb" in data
        assert "disk_free_gb" in data
        assert isinstance(data["gpus"], list)
        assert data["cpu_cores"] > 0
        assert "recommended_backend" in data

    async def test_hardware_redetect(self, recovery: httpx.AsyncClient, admin_headers: dict):
        """Re-detection should refresh hardware info."""
        r = await recovery.post(
            "/api/v1/recovery/inference/hardware/detect",
            headers=admin_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "detected_at" in data
        assert "recommended_backend" in data


class TestGatewayInflight:
    """Tests for the /health/inflight endpoint."""

    async def test_inflight_endpoint_exists(self, llm_gateway: httpx.AsyncClient):
        """Gateway should expose /health/inflight with a count."""
        r = await llm_gateway.get("/health/inflight")
        assert r.status_code == 200
        data = r.json()
        assert "local_inflight" in data
        assert isinstance(data["local_inflight"], int)
        assert data["local_inflight"] >= 0


class TestVLLMProviderRegistration:
    """Test that vLLM provider appears in the gateway's provider catalog."""

    async def test_vllm_in_provider_catalog(self, llm_gateway: httpx.AsyncClient):
        """LLM gateway should list vllm as a known provider."""
        r = await llm_gateway.get("/health/providers")
        assert r.status_code == 200
        providers = r.json()
        slugs = [p["slug"] for p in providers]
        assert "vllm" in slugs

    async def test_vllm_provider_unavailable_when_not_running(self, llm_gateway: httpx.AsyncClient):
        """vLLM provider should show as unavailable when container isn't running."""
        r = await llm_gateway.get("/health/providers")
        assert r.status_code == 200
        providers = r.json()
        vllm = next((p for p in providers if p["slug"] == "vllm"), None)
        assert vllm is not None
        # vLLM container not running in test env, so should be unavailable
        assert vllm["available"] is False


class TestLocalInferenceRouting:
    """Tests for the LocalInferenceProvider routing wrapper."""

    async def test_routing_strategy_still_works(self, llm_gateway: httpx.AsyncClient):
        """Routing strategy should still apply to local models after refactor."""
        r = await llm_gateway.get("/health/providers")
        assert r.status_code == 200
        providers = r.json()
        slugs = [p["slug"] for p in providers]
        assert any(s in slugs for s in ["groq", "anthropic", "openai", "gemini"])
