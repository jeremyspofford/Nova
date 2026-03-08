"""Trusted networks integration tests — network status, auth bypass, config seeding."""
from __future__ import annotations

import httpx
import pytest


class TestNetworkStatus:
    """GET /api/v1/auth/network-status — public endpoint."""

    async def test_returns_client_ip_and_trust(self, orchestrator: httpx.AsyncClient):
        resp = await orchestrator.get("/api/v1/auth/network-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "client_ip" in data
        assert "trusted" in data
        assert isinstance(data["trusted"], bool)
        # From localhost/Docker bridge, we should be trusted by default
        assert data["trusted"] is True

    async def test_ip_is_valid(self, orchestrator: httpx.AsyncClient):
        resp = await orchestrator.get("/api/v1/auth/network-status")
        ip = resp.json()["client_ip"]
        # Should be a valid IPv4 or IPv6 address (not empty or "unknown")
        assert ip and ip != "unknown"


class TestAuthProvidersTrustedField:
    """GET /api/v1/auth/providers — includes trusted_network field."""

    async def test_providers_includes_trusted_network(self, orchestrator: httpx.AsyncClient):
        resp = await orchestrator.get("/api/v1/auth/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "trusted_network" in data
        assert isinstance(data["trusted_network"], bool)
        # From localhost/Docker bridge, should be trusted
        assert data["trusted_network"] is True


class TestTrustedNetworkAuthBypass:
    """Trusted network requests should bypass auth — no credentials needed."""

    async def test_admin_endpoint_no_credentials(self, orchestrator: httpx.AsyncClient):
        """Config endpoint requires admin auth, but trusted network bypasses it."""
        resp = await orchestrator.get("/api/v1/config")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))

    async def test_agent_list_no_credentials(self, orchestrator: httpx.AsyncClient):
        """Agent list requires API key auth, but trusted network bypasses it."""
        resp = await orchestrator.get("/api/v1/agents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_user_endpoint_no_credentials(self, orchestrator: httpx.AsyncClient):
        """User-scoped endpoints accept trusted network requests (auth dep passes).

        /auth/me returns 404 because the synthetic admin has no DB record,
        but the auth dependency itself passes — it doesn't return 401.
        We verify with /conversations which also uses UserDep.
        """
        resp = await orchestrator.get("/api/v1/conversations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestTrustedNetworkConfigSeeded:
    """Migration 015 seeds platform_config with trusted network keys."""

    async def test_trusted_networks_key_exists(self, orchestrator: httpx.AsyncClient):
        resp = await orchestrator.get("/api/v1/config")
        assert resp.status_code == 200
        keys = {entry["key"] for entry in resp.json()}
        assert "trusted_networks" in keys

    async def test_trusted_proxy_header_key_exists(self, orchestrator: httpx.AsyncClient):
        resp = await orchestrator.get("/api/v1/config")
        assert resp.status_code == 200
        keys = {entry["key"] for entry in resp.json()}
        assert "trusted_proxy_header" in keys
