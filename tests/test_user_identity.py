"""Integration tests for user identity features.

Tests the user profile endpoint, pool stats, and identity-related
features of the engram memory system.
"""
import httpx
import pytest
import pytest_asyncio

MEMORY_URL = "http://localhost:8002/api/v1/engrams"


class TestPoolStats:
    """Verify /stats includes user_profile breakdown."""

    async def test_stats_has_user_profile(self, memory):
        """GET /stats should include a user_profile section."""
        resp = await memory.get(f"{MEMORY_URL}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "user_profile" in data, "Stats response missing user_profile section"
        profile = data["user_profile"]
        assert "entity_count" in profile
        assert "fact_count" in profile
        assert "preference_count" in profile


class TestUserProfile:
    """Verify GET /user-profile returns personal memory data."""

    async def test_user_profile_endpoint(self, memory):
        """GET /user-profile should return entities, facts, preferences."""
        resp = await memory.get(f"{MEMORY_URL}/user-profile")
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert "facts" in data
        assert "preferences" in data
        assert isinstance(data["entities"], list)
        assert isinstance(data["facts"], list)
        assert isinstance(data["preferences"], list)

    async def test_user_profile_entity_shape(self, memory):
        """Each entity should have required fields."""
        resp = await memory.get(f"{MEMORY_URL}/user-profile")
        data = resp.json()
        if not data["entities"]:
            pytest.skip("No entities in user profile")
        entity = data["entities"][0]
        for field in ("id", "name", "confidence", "learned_at"):
            assert field in entity, f"Entity missing field: {field}"

    async def test_user_profile_excludes_non_personal(self):
        """External-sourced entities should not appear in user profile."""
        async with httpx.AsyncClient(timeout=30) as c:
            # Ingest an external entity
            r = await c.post(f"{MEMORY_URL}/ingest", json={
                "raw_text": "nova-test-external-entity: ExternalCorp is a company",
                "source_type": "external",
            })
            assert r.status_code == 201

            # Check user profile
            resp = await c.get(f"{MEMORY_URL}/user-profile")
            assert resp.status_code == 200
            data = resp.json()

            # The external entity should NOT appear
            entity_names = [e["name"].lower() for e in data["entities"]]
            assert "externalcorp" not in entity_names, (
                "External-sourced entity appeared in user profile"
            )
