"""Recovery service integration tests — status, backups, services, factory reset."""
from __future__ import annotations

import os

import httpx
import pytest

# Destructive factory-reset tests are opt-in — they wipe live data on the dev system.
# Set NOVA_ALLOW_DESTRUCTIVE_TESTS=1 to enable.
DESTRUCTIVE_ALLOWED = os.getenv("NOVA_ALLOW_DESTRUCTIVE_TESTS") == "1"


class TestRecoveryStatus:
    async def test_status_overview(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/status")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    async def test_list_services(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/services")
        assert resp.status_code == 200
        services = resp.json()
        assert isinstance(services, list)
        # Should have at least a few Nova services
        if len(services) > 0:
            svc = services[0]
            assert "service" in svc or "name" in svc or "container_name" in svc


class TestBackups:
    async def test_list_backups(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/backups")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_delete_backup(self, recovery: httpx.AsyncClient, admin_headers: dict):
        # Create
        resp = await recovery.post("/api/v1/recovery/backups", headers=admin_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        filename = data.get("filename") or data.get("name")
        assert filename is not None

        # Delete the test backup
        resp = await recovery.delete(
            f"/api/v1/recovery/backups/{filename}",
            headers=admin_headers,
        )
        assert resp.status_code == 200


class TestFactoryReset:
    async def test_list_categories(self, recovery: httpx.AsyncClient):
        resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        assert resp.status_code == 200
        categories = resp.json()
        assert isinstance(categories, list)
        assert len(categories) >= 10, "Expected the full PRIV-003 category set"

        for cat in categories:
            assert "key" in cat
            assert "label" in cat
            assert "description" in cat
            assert "default_keep" in cat
            # destructive_warning may be None
            assert "destructive_warning" in cat

    async def test_categories_include_priv_003_coverage(self, recovery: httpx.AsyncClient):
        """Every user-data surface audited in PRIV-003 must be covered."""
        resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        assert resp.status_code == 200
        keys = {c["key"] for c in resp.json()}

        required = {
            "chat_history",
            "task_pipeline_history",
            "cortex_state",
            "intel_data",
            "knowledge_data",
            "runtime_caches",
            "memory_and_knowledge",
            "api_keys",
            "linked_accounts",
            "platform_config",
            "users_and_auth",
            "backups",
        }
        assert required <= keys, f"Missing categories: {required - keys}"

    async def test_destructive_categories_have_warnings(self, recovery: httpx.AsyncClient):
        """users_and_auth and backups must carry destructive_warning copy."""
        resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        by_key = {c["key"]: c for c in resp.json()}
        assert by_key["users_and_auth"]["destructive_warning"], \
            "users_and_auth must warn about cascaded deletes"
        assert by_key["backups"]["destructive_warning"], \
            "backups must warn about losing recovery archives"

    async def test_defaults_match_option_a(self, recovery: httpx.AsyncClient):
        """Option A (Selective Reset) — these 6 should be preserved by default."""
        resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        by_key = {c["key"]: c for c in resp.json()}

        defaults_keep = {
            "memory_and_knowledge",
            "api_keys",
            "linked_accounts",
            "platform_config",
            "users_and_auth",
            "backups",
        }
        defaults_wipe = {
            "chat_history",
            "task_pipeline_history",
            "cortex_state",
            "intel_data",
            "knowledge_data",
            "runtime_caches",
        }
        for key in defaults_keep:
            assert by_key[key]["default_keep"] is True, f"{key} should default to keep"
        for key in defaults_wipe:
            assert by_key[key]["default_keep"] is False, f"{key} should default to wipe"

    async def test_reset_requires_confirmation(self, recovery: httpx.AsyncClient, admin_headers: dict):
        """Missing/wrong confirm string returns 400 — guards against accidental POSTs."""
        resp = await recovery.post(
            "/api/v1/recovery/factory-reset",
            json={"keep": [], "confirm": "yes"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_reset_requires_admin(self, recovery: httpx.AsyncClient):
        """Unauthenticated callers must be rejected before any wipe happens."""
        resp = await recovery.post(
            "/api/v1/recovery/factory-reset",
            json={"keep": [], "confirm": "RESET"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.skipif(not DESTRUCTIVE_ALLOWED, reason="set NOVA_ALLOW_DESTRUCTIVE_TESTS=1 to run")
    async def test_reset_keep_all_is_noop(self, recovery: httpx.AsyncClient, admin_headers: dict):
        """Keeping every category should wipe nothing — useful smoke test."""
        cats_resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        all_keys = [c["key"] for c in cats_resp.json()]

        resp = await recovery.post(
            "/api/v1/recovery/factory-reset",
            json={"keep": all_keys, "confirm": "RESET"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["wiped"] == []
        assert set(data["kept"]) == set(all_keys)
        assert data["stats"]["tables_truncated"] == 0
        assert data["stats"]["filesystem_files_removed"] == 0

    @pytest.mark.skipif(not DESTRUCTIVE_ALLOWED, reason="set NOVA_ALLOW_DESTRUCTIVE_TESTS=1 to run")
    async def test_reset_runtime_caches_only(
        self, recovery: httpx.AsyncClient, admin_headers: dict
    ):
        """Wiping only runtime_caches should report truncated cache table(s) +
        deleted redis keys, leave everything else alone."""
        cats_resp = await recovery.get("/api/v1/recovery/factory-reset/categories")
        all_keys = [c["key"] for c in cats_resp.json()]
        keep = [k for k in all_keys if k != "runtime_caches"]

        resp = await recovery.post(
            "/api/v1/recovery/factory-reset",
            json={"keep": keep, "confirm": "RESET"},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["wiped"] == ["runtime_caches"]
        # embedding_cache is the only table in runtime_caches
        assert data["stats"]["tables_truncated"] <= 1


class TestTroubleshoot:
    async def test_troubleshoot_requires_auth(self, recovery: httpx.AsyncClient):
        resp = await recovery.post(
            "/api/v1/recovery/troubleshoot/chat",
            json={"message": "Why is my service down?", "history": []},
        )
        assert resp.status_code in (401, 403)

    async def test_troubleshoot_returns_response(
        self, recovery: httpx.AsyncClient, admin_headers: dict
    ):
        resp = await recovery.post(
            "/api/v1/recovery/troubleshoot/chat",
            json={"message": "What services are running?", "history": []},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "response" in data
        assert "provider" in data
        # provider may be null if no LLM is configured
        if data["provider"] is not None:
            assert data["provider"] in ("anthropic", "openai", "groq", "ollama")

    async def test_troubleshoot_with_history(
        self, recovery: httpx.AsyncClient, admin_headers: dict
    ):
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]
        resp = await recovery.post(
            "/api/v1/recovery/troubleshoot/chat",
            json={"message": "Check postgres", "history": history},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "response" in data
        assert "provider" in data

    async def test_troubleshoot_empty_message(
        self, recovery: httpx.AsyncClient, admin_headers: dict
    ):
        resp = await recovery.post(
            "/api/v1/recovery/troubleshoot/chat",
            json={"message": "", "history": []},
            headers=admin_headers,
        )
        # Accept either a valid response or a validation error
        assert resp.status_code in (200, 422), resp.text
        if resp.status_code == 200:
            data = resp.json()
            assert "response" in data
            assert "provider" in data
