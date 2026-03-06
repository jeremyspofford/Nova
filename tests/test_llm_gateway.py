"""LLM Gateway integration tests — model listing, discovery (no LLM calls)."""
from __future__ import annotations

import httpx
import pytest


class TestModelListing:
    async def test_native_models_endpoint(self, llm_gateway: httpx.AsyncClient):
        resp = await llm_gateway.get("/models")
        assert resp.status_code == 200
        models = resp.json()
        assert isinstance(models, list)

    async def test_openai_compat_models(self, llm_gateway: httpx.AsyncClient):
        resp = await llm_gateway.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        # Could be OpenAI format {"object":"list","data":[...]} or plain list
        if isinstance(data, dict):
            assert "data" in data
            assert isinstance(data["data"], list)
        else:
            assert isinstance(data, list)


class TestDiscovery:
    async def test_discover_providers(self, llm_gateway: httpx.AsyncClient):
        resp = await llm_gateway.get("/v1/models/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))


class TestDualHealthPaths:
    """LLM Gateway exposes health at both / and /v1/ prefixes."""

    async def test_v1_health_live(self, llm_gateway: httpx.AsyncClient):
        resp = await llm_gateway.get("/v1/health/live")
        assert resp.status_code == 200

    async def test_v1_health_ready(self, llm_gateway: httpx.AsyncClient):
        resp = await llm_gateway.get("/v1/health/ready")
        assert resp.status_code == 200
