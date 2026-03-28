"""Integration tests for memory consolidation system.

These tests verify:
- Consolidation is running and producing log entries
- Consolidation log has required fields for monitoring
- Memory stats endpoint works for agent self-awareness
- Manual consolidation trigger is functional
"""
import httpx
import pytest
import pytest_asyncio

MEMORY_URL = "http://localhost:8002/api/v1/engrams"


class TestConsolidationLog:
    """Verify the consolidation log is populated and has correct shape."""

    async def test_consolidation_log_endpoint(self, memory):
        """GET /consolidation-log should return entries."""
        resp = await memory.get(f"{MEMORY_URL}/consolidation-log", params={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert isinstance(data["entries"], list)

    async def test_consolidation_log_entry_shape(self, memory):
        """Each consolidation log entry must have required fields for monitoring."""
        resp = await memory.get(f"{MEMORY_URL}/consolidation-log", params={"limit": 1})
        data = resp.json()
        if not data["entries"]:
            pytest.skip("No consolidation log entries yet")

        entry = data["entries"][0]
        required_fields = {
            "id", "trigger", "engrams_reviewed", "schemas_created",
            "edges_strengthened", "edges_pruned", "engrams_merged",
            "contradictions_resolved", "topics_created",
            "duration_ms", "created_at",
        }
        missing = required_fields - set(entry.keys())
        assert not missing, f"Consolidation log entry missing fields: {missing}"

    async def test_consolidation_log_has_trigger_type(self, memory):
        """Trigger field must be one of the expected types."""
        resp = await memory.get(f"{MEMORY_URL}/consolidation-log", params={"limit": 10})
        data = resp.json()
        valid_triggers = {"idle", "threshold", "nightly", "manual"}
        for entry in data["entries"]:
            assert entry["trigger"] in valid_triggers, (
                f"Unexpected trigger type: {entry['trigger']}"
            )

    async def test_consolidation_log_ordered_by_recency(self, memory):
        """Log entries should be ordered newest-first."""
        resp = await memory.get(f"{MEMORY_URL}/consolidation-log", params={"limit": 5})
        entries = resp.json()["entries"]
        if len(entries) < 2:
            pytest.skip("Need at least 2 entries to verify ordering")

        for i in range(len(entries) - 1):
            assert entries[i]["created_at"] >= entries[i + 1]["created_at"], (
                "Consolidation log entries should be ordered newest-first"
            )


class TestMemoryStats:
    """Verify memory stats endpoint works — needed for agent self-awareness."""

    async def test_stats_endpoint(self, memory):
        """GET /stats must return memory system health data."""
        resp = await memory.get(f"{MEMORY_URL}/stats")
        assert resp.status_code == 200
        data = resp.json()

        # These fields are needed for agents to verify memory health
        assert "total_engrams" in data or "engram_count" in data, (
            "Stats must include engram count"
        )

    async def test_stats_has_source_breakdown(self, memory):
        """Stats should include breakdown by source type."""
        resp = await memory.get(f"{MEMORY_URL}/stats")
        data = resp.json()
        # The stats should give some indication of where memories come from
        has_breakdown = (
            "by_source_type" in data
            or "sources" in data
            or "source_count" in data
        )
        assert has_breakdown, "Stats should include source type breakdown"


class TestConsolidationTrigger:
    """Verify manual consolidation trigger works."""

    async def test_trigger_consolidation(self):
        """POST /consolidate should trigger a cycle (or report already running)."""
        # Use a dedicated client with longer timeout — consolidation can take minutes
        async with httpx.AsyncClient(timeout=180.0) as c:
            resp = await c.post(f"{MEMORY_URL}/consolidate")
            assert resp.status_code == 200
            data = resp.json()
            # Either ran successfully or was skipped (already running)
            assert "skipped" in data or "engrams_reviewed" in data or "trigger" in data, (
                f"Unexpected consolidation response: {data}"
            )


class TestConsolidationRunning:
    """Verify consolidation is actually running (not silently broken)."""

    async def test_recent_consolidation_exists(self, memory):
        """At least one consolidation should have run in the last 24 hours."""
        from datetime import datetime, timezone, timedelta

        resp = await memory.get(f"{MEMORY_URL}/consolidation-log", params={"limit": 1})
        data = resp.json()
        if not data["entries"]:
            pytest.fail("No consolidation has ever run — daemon may not be started")

        last_run = datetime.fromisoformat(data["entries"][0]["created_at"])
        age = datetime.now(timezone.utc) - last_run
        assert age < timedelta(hours=24), (
            f"Last consolidation was {age} ago — daemon may be stuck or dead"
        )
