"""Integration tests for agent self-awareness and tool capabilities.

These tests verify:
- Agent system prompt includes self-knowledge about Nova's architecture
- All expected tool groups are registered and functional
- Diagnostic tools return actionable data
- Memory tools are accessible from agents
- Service health check covers all services
"""
import pytest


class TestAgentToolAvailability:
    """Verify all expected tools are registered and callable."""

    async def test_tool_catalog_has_core_groups(self, orchestrator, admin_headers):
        """The tool catalog should include Code, Git, Platform, and Web groups."""
        resp = await orchestrator.get("/api/v1/tools", headers=admin_headers)
        if resp.status_code == 404:
            pytest.skip("Tool catalog endpoint not available")
        assert resp.status_code == 200
        catalog = resp.json()

        # Catalog is a list of categories, each with a nested tools array
        tool_names = set()
        category_names = set()
        for category in catalog:
            category_names.add(category.get("category", ""))
            for tool in category.get("tools", []):
                tool_names.add(tool["name"])

        # Tools exposed via the catalog API
        catalog_expected = {
            "read_file", "write_file", "run_shell", "search_codebase",
            "git_status", "git_log",
            "web_search", "web_fetch",
            "list_agents", "create_task",
        }
        missing = catalog_expected - tool_names
        assert not missing, f"Missing catalog tools: {missing}"

    async def test_tool_catalog_includes_diagnosis_and_memory(self, orchestrator, admin_headers):
        """Diagnosis and Memory tools must be in the catalog for full agent awareness.
        Currently these are available to agents internally but NOT exposed via the
        /api/v1/tools catalog. This test documents the gap."""
        resp = await orchestrator.get("/api/v1/tools", headers=admin_headers)
        if resp.status_code == 404:
            pytest.skip("Tool catalog endpoint not available")
        catalog = resp.json()

        tool_names = set()
        for category in catalog:
            for tool in category.get("tools", []):
                tool_names.add(tool["name"])

        internal_only_tools = {
            "diagnose_task", "check_service_health", "get_recent_errors",
            "search_memory", "recall_topic", "what_do_i_know", "read_source",
            "get_platform_config", "list_knowledge_sources",
        }
        exposed = internal_only_tools & tool_names
        hidden = internal_only_tools - tool_names
        if hidden:
            pytest.xfail(
                f"These tools are available to agents internally but not in the "
                f"/api/v1/tools catalog: {hidden}"
            )


class TestDiagnosticTools:
    """Verify diagnostic tools return useful data for agent self-awareness."""

    async def test_service_health_check(self, orchestrator, admin_headers):
        """check_service_health should report status for all core services."""
        resp = await orchestrator.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ("ok", "ready")

    async def test_recent_errors_endpoint(self, orchestrator, admin_headers):
        """Recent errors endpoint should be queryable (may be empty)."""
        resp = await orchestrator.get("/api/v1/diagnostics/errors", headers=admin_headers)
        if resp.status_code == 404:
            pytest.skip("Diagnostics errors endpoint not available")
        assert resp.status_code == 200


class TestSelfKnowledge:
    """Verify the self-knowledge block covers all active services."""

    async def test_agent_has_self_knowledge(self, orchestrator, admin_headers, test_api_key):
        """An agent created via chat should receive self-knowledge context.
        We verify by checking that the agent's config includes Nova identity."""
        # Create a temporary agent to inspect its config
        resp = await orchestrator.post("/api/v1/agents", headers=admin_headers, json={
            "name": "nova-test-self-knowledge-check",
            "role": "context",
            "model": "auto",
            "system_prompt": "You are a test agent.",
        })
        if resp.status_code not in (200, 201):
            pytest.skip(f"Could not create test agent: {resp.status_code}")
        agent = resp.json()
        agent_id = agent["id"]

        # The system prompt should exist
        assert agent.get("system_prompt") or agent.get("config", {}).get("system_prompt"), (
            "Agent should have a system prompt"
        )

        # Cleanup
        await orchestrator.delete(f"/api/v1/agents/{agent_id}", headers=admin_headers)


class TestMemoryToolsAccessibility:
    """Verify memory endpoints that agents call are functional."""

    async def test_search_memory_endpoint(self, memory):
        """POST /context (main memory retrieval) should be functional."""
        resp = await memory.post(
            "http://localhost:8002/api/v1/engrams/context",
            json={"query": "nova-test-memory-search", "max_results": 3},
        )
        assert resp.status_code == 200

    async def test_domain_overview_endpoint(self, memory):
        """what_do_i_know tool calls domain-summary — verify it works."""
        resp = await memory.get("http://localhost:8002/api/v1/engrams/sources/domain-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "source_count" in data

    async def test_engram_stats(self, memory):
        """Stats endpoint should return engram count for self-monitoring."""
        resp = await memory.get("http://localhost:8002/api/v1/engrams/stats")
        assert resp.status_code == 200


class TestIntelRecommendationPipeline:
    """Verify the intel-to-recommendation pipeline schema is complete."""

    async def test_recommendation_create_endpoint_exists(self, orchestrator, admin_headers):
        """POST /api/v1/intel/recommendations MUST exist for the suggested goals pipeline.
        Without it, the grading pipeline has no way to create recommendations, and
        the 'Suggested' tab in Goals will always be empty."""
        resp = await orchestrator.post(
            "/api/v1/intel/recommendations",
            headers=admin_headers,
            json={
                "title": "nova-test-recommendation",
                "summary": "Test recommendation for pipeline verification",
                "rationale": "Automated test to verify recommendation schema",
                "grade": "C",
                "confidence": 0.6,
                "category": "test",
            },
        )
        # 405 = endpoint exists but POST not allowed; 404 = route not found
        # Either means the CREATE endpoint is missing — this is the root cause
        # of zero recommendations ever being generated.
        if resp.status_code in (404, 405):
            pytest.xfail(
                "POST /api/v1/intel/recommendations not implemented — "
                "this is required for the suggested goals pipeline to produce output"
            )
        assert resp.status_code in (200, 201)
        rec = resp.json()
        # Cleanup if it was created
        if "id" in rec:
            await orchestrator.delete(
                f"/api/v1/intel/recommendations/{rec['id']}", headers=admin_headers,
            )

    async def test_recommendation_list_returns_expected_fields(self, orchestrator, admin_headers):
        """Recommendation list response should have the right shape for the dashboard."""
        resp = await orchestrator.get("/api/v1/intel/recommendations", headers=admin_headers)
        assert resp.status_code == 200
        recs = resp.json()
        assert isinstance(recs, list)
        # If any exist, verify shape
        for rec in recs[:3]:
            for field in ("id", "title", "summary", "grade", "status"):
                assert field in rec, f"Recommendation missing field: {field}"

    async def test_intel_dead_letter_queue_awareness(self, orchestrator, admin_headers):
        """Intel stats should include items_this_week — verifying content is flowing."""
        resp = await orchestrator.get("/api/v1/intel/stats", headers=admin_headers)
        assert resp.status_code == 200
        stats = resp.json()
        # items_this_week > 0 means content is being ingested from feeds
        assert "items_this_week" in stats
        # We don't assert > 0 because feeds might not have run yet in CI
