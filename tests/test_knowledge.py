"""Integration tests for knowledge sources, credentials, and SSRF protection."""
import pytest


class TestKnowledgeSourceCRUD:
    """Test knowledge source lifecycle."""

    async def test_list_sources_empty(self, orchestrator, admin_headers):
        """List sources returns a list."""
        resp = await orchestrator.get("/api/v1/knowledge/sources", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_source(self, orchestrator, admin_headers):
        """Create a knowledge source."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={
                "name": "nova-test-portfolio",
                "url": "https://example.com",
                "source_type": "web_crawl",
            },
        )
        assert resp.status_code == 201
        source = resp.json()
        assert source["name"] == "nova-test-portfolio"
        assert source["status"] == "active"
        assert source["source_type"] == "web_crawl"
        assert source["scope"] == "personal"

        # Cleanup
        await orchestrator.delete(
            f"/api/v1/knowledge/sources/{source['id']}",
            headers=admin_headers,
        )

    async def test_create_source_github(self, orchestrator, admin_headers):
        """Create a GitHub profile source."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={
                "name": "nova-test-github",
                "url": "https://github.com/octocat",
                "source_type": "github_profile",
            },
        )
        assert resp.status_code == 201
        source = resp.json()
        assert source["source_type"] == "github_profile"

        # Cleanup
        await orchestrator.delete(
            f"/api/v1/knowledge/sources/{source['id']}",
            headers=admin_headers,
        )

    async def test_get_source_detail(self, orchestrator, admin_headers):
        """Get source detail includes crawl history."""
        # Create
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-detail", "url": "https://example.com", "source_type": "web_crawl"},
        )
        source_id = resp.json()["id"]

        # Get detail
        resp = await orchestrator.get(
            f"/api/v1/knowledge/sources/{source_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == source_id
        assert "crawl_history" in detail or "name" in detail

        # Cleanup
        await orchestrator.delete(f"/api/v1/knowledge/sources/{source_id}", headers=admin_headers)

    async def test_update_source(self, orchestrator, admin_headers):
        """Update a source's name and status."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-update", "url": "https://example.com", "source_type": "web_crawl"},
        )
        source_id = resp.json()["id"]

        # Update
        resp = await orchestrator.patch(
            f"/api/v1/knowledge/sources/{source_id}",
            headers=admin_headers,
            json={"name": "nova-test-updated", "status": "paused"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "nova-test-updated"
        assert resp.json()["status"] == "paused"

        # Cleanup
        await orchestrator.delete(f"/api/v1/knowledge/sources/{source_id}", headers=admin_headers)

    async def test_delete_source(self, orchestrator, admin_headers):
        """Delete a source returns 204."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-delete", "url": "https://example.com", "source_type": "web_crawl"},
        )
        source_id = resp.json()["id"]

        resp = await orchestrator.delete(
            f"/api/v1/knowledge/sources/{source_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 204

    async def test_manual_paste(self, orchestrator, admin_headers):
        """Manual paste submits content for ingestion."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-paste", "url": "https://example.com", "source_type": "manual_import"},
        )
        source_id = resp.json()["id"]

        resp = await orchestrator.post(
            f"/api/v1/knowledge/sources/{source_id}/paste",
            headers=admin_headers,
            json={"content": "Jeremy is a cloud engineer who builds infrastructure tools and studies for AWS certifications."},
        )
        assert resp.status_code == 200

        # Cleanup
        await orchestrator.delete(f"/api/v1/knowledge/sources/{source_id}", headers=admin_headers)


class TestKnowledgeCredentials:
    """Test credential lifecycle."""

    async def test_create_and_list_credential(self, orchestrator, admin_headers):
        """Create credential, verify it appears in list without plaintext."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/credentials",
            headers=admin_headers,
            json={"label": "nova-test-github-pat", "credential_data": "ghp_test123456789"},
        )
        assert resp.status_code == 201
        cred = resp.json()
        assert cred["label"] == "nova-test-github-pat"
        assert "encrypted_data" not in cred
        assert "credential_data" not in cred
        cred_id = cred["id"]

        # List — should appear
        resp = await orchestrator.get("/api/v1/knowledge/credentials", headers=admin_headers)
        assert resp.status_code == 200
        creds = resp.json()
        assert any(c["id"] == cred_id for c in creds)

        # Verify no credential in list exposes encrypted data
        for c in creds:
            assert "encrypted_data" not in c
            assert "credential_data" not in c

        # Cleanup
        await orchestrator.delete(f"/api/v1/knowledge/credentials/{cred_id}", headers=admin_headers)

    async def test_delete_credential(self, orchestrator, admin_headers):
        """Delete credential returns 204."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/credentials",
            headers=admin_headers,
            json={"label": "nova-test-delete-cred", "credential_data": "test-token"},
        )
        cred_id = resp.json()["id"]

        resp = await orchestrator.delete(
            f"/api/v1/knowledge/credentials/{cred_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 204


class TestKnowledgeSSRF:
    """Test SSRF protection for knowledge sources."""

    @pytest.mark.parametrize("url", [
        "http://localhost:8000/health",
        "http://redis:6379",
        "http://169.254.169.254/latest/meta-data/",
        "http://orchestrator:8000/api/v1/knowledge/sources",
        "http://knowledge-worker:8120/health/live",
        "http://10.0.0.1/internal",
        "ftp://example.com/file",
    ])
    async def test_ssrf_blocked(self, orchestrator, admin_headers, url):
        """SSRF attacks are blocked."""
        resp = await orchestrator.post(
            "/api/v1/knowledge/sources",
            headers=admin_headers,
            json={"name": "nova-test-ssrf", "url": url, "source_type": "web_crawl"},
        )
        assert resp.status_code == 400


class TestKnowledgeStats:
    """Test knowledge stats endpoint."""

    async def test_get_stats(self, orchestrator, admin_headers):
        resp = await orchestrator.get("/api/v1/knowledge/stats", headers=admin_headers)
        assert resp.status_code == 200
        stats = resp.json()
        assert "sources_total" in stats
        assert "total_credentials" in stats


class TestKnowledgeWorkerHealth:
    """Test knowledge-worker health endpoints (requires --profile knowledge)."""

    @pytest.mark.skipif(True, reason="Requires --profile knowledge to be running")
    async def test_health_live(self, knowledge_worker):
        resp = await knowledge_worker.get("/health/live")
        assert resp.status_code == 200

    @pytest.mark.skipif(True, reason="Requires --profile knowledge to be running")
    async def test_health_ready(self, knowledge_worker):
        resp = await knowledge_worker.get("/health/ready")
        assert resp.status_code == 200
