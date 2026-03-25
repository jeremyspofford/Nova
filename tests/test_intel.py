"""Integration tests for Intel endpoints."""
import pytest


class TestIntelFeeds:
    async def test_list_feeds(self, orchestrator, admin_headers):
        """Default feeds should be seeded by migration 040."""
        resp = await orchestrator.get("/api/v1/intel/feeds", headers=admin_headers)
        assert resp.status_code == 200
        feeds = resp.json()
        assert isinstance(feeds, list)
        # Migration 040 seeds 14 default feeds
        assert len(feeds) >= 14

    async def test_create_and_delete_feed(self, orchestrator, admin_headers):
        """Create a feed, verify it appears, then delete it."""
        resp = await orchestrator.post("/api/v1/intel/feeds", headers=admin_headers, json={
            "name": "nova-test-feed",
            "url": "https://example.com/test-rss.xml",
            "feed_type": "rss",
            "category": "test",
        })
        assert resp.status_code == 201
        feed = resp.json()
        feed_id = feed["id"]
        assert feed["name"] == "nova-test-feed"
        assert feed["feed_type"] == "rss"
        assert feed["enabled"] is True

        # Cleanup
        resp = await orchestrator.delete(f"/api/v1/intel/feeds/{feed_id}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_ssrf_blocked_localhost(self, orchestrator, admin_headers):
        """SSRF: localhost should be rejected."""
        resp = await orchestrator.post("/api/v1/intel/feeds", headers=admin_headers, json={
            "name": "nova-test-ssrf",
            "url": "http://localhost:8000/health/live",
            "feed_type": "page",
        })
        assert resp.status_code == 400

    async def test_ssrf_blocked_internal(self, orchestrator, admin_headers):
        """SSRF: Docker-internal hostnames should be rejected."""
        resp = await orchestrator.post("/api/v1/intel/feeds", headers=admin_headers, json={
            "name": "nova-test-ssrf-internal",
            "url": "http://redis:6379/",
            "feed_type": "page",
        })
        assert resp.status_code == 400

    async def test_update_feed(self, orchestrator, admin_headers):
        """Create, update, verify, delete."""
        # Create
        resp = await orchestrator.post("/api/v1/intel/feeds", headers=admin_headers, json={
            "name": "nova-test-update",
            "url": "https://example.com/update-test.xml",
            "feed_type": "rss",
        })
        feed_id = resp.json()["id"]

        # Update
        resp = await orchestrator.patch(f"/api/v1/intel/feeds/{feed_id}", headers=admin_headers, json={
            "enabled": False,
            "check_interval_seconds": 7200,
        })
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False
        assert resp.json()["check_interval_seconds"] == 7200

        # Cleanup
        await orchestrator.delete(f"/api/v1/intel/feeds/{feed_id}", headers=admin_headers)


class TestIntelRecommendations:
    async def test_list_recommendations_empty(self, orchestrator, admin_headers):
        """List recommendations returns empty array initially."""
        resp = await orchestrator.get("/api/v1/intel/recommendations", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_with_filters(self, orchestrator, admin_headers):
        """List recommendations with query filters."""
        resp = await orchestrator.get(
            "/api/v1/intel/recommendations",
            headers=admin_headers,
            params={"status": "pending", "limit": "10"},
        )
        assert resp.status_code == 200


class TestIntelStats:
    async def test_get_stats(self, orchestrator, admin_headers):
        """Stats endpoint returns expected shape."""
        resp = await orchestrator.get("/api/v1/intel/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items_this_week" in data
        assert "active_feeds" in data
        assert "grade_a" in data
        assert "grade_b" in data
        assert "grade_c" in data
        assert "total_recommendations" in data


class TestGoalComments:
    async def test_goal_comment_crud(self, orchestrator, admin_headers):
        """Create goal, add comment, list, delete comment, delete goal."""
        # Create goal
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-comment-goal",
        })
        assert resp.status_code == 201
        goal_id = resp.json()["id"]

        # Add comment
        resp = await orchestrator.post(
            f"/api/v1/goals/{goal_id}/comments",
            headers=admin_headers,
            json={"author_name": "Test User", "body": "Test comment body"},
        )
        assert resp.status_code == 201
        comment = resp.json()
        assert comment["body"] == "Test comment body"
        assert comment["author_type"] == "human"
        comment_id = comment["id"]

        # List comments
        resp = await orchestrator.get(f"/api/v1/goals/{goal_id}/comments", headers=admin_headers)
        assert resp.status_code == 200
        comments = resp.json()
        assert len(comments) == 1
        assert comments[0]["id"] == comment_id

        # Delete comment
        resp = await orchestrator.delete(
            f"/api/v1/goals/{goal_id}/comments/{comment_id}",
            headers=admin_headers,
        )
        assert resp.status_code == 204

        # Verify deleted
        resp = await orchestrator.get(f"/api/v1/goals/{goal_id}/comments", headers=admin_headers)
        assert len(resp.json()) == 0

        # Cleanup
        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)


class TestSystemGoalProtection:
    async def test_cannot_delete_system_goal(self, orchestrator, admin_headers):
        """System goals (created_via='system') cannot be deleted."""
        resp = await orchestrator.delete(
            "/api/v1/goals/d0000000-0000-0000-0000-000000000001",
            headers=admin_headers,
        )
        assert resp.status_code == 403

    async def test_system_goals_exist(self, orchestrator, admin_headers):
        """System goals should be seeded by migration 040."""
        for goal_id in [
            "d0000000-0000-0000-0000-000000000001",
            "d0000000-0000-0000-0000-000000000002",
            "d0000000-0000-0000-0000-000000000003",
        ]:
            resp = await orchestrator.get(f"/api/v1/goals/{goal_id}", headers=admin_headers)
            assert resp.status_code == 200
            goal = resp.json()
            assert goal["created_via"] == "system"
            assert goal["schedule_cron"] is not None


class TestGoalMaturation:
    async def test_goal_has_maturation_fields(self, orchestrator, admin_headers):
        """Goals should include maturation fields in response."""
        resp = await orchestrator.post("/api/v1/goals", headers=admin_headers, json={
            "title": "nova-test-maturation",
        })
        assert resp.status_code == 201
        goal = resp.json()
        goal_id = goal["id"]

        # Maturation fields should be present (null by default)
        assert "maturation_status" in goal
        assert goal["maturation_status"] is None
        assert "complexity" in goal

        # Cleanup
        await orchestrator.delete(f"/api/v1/goals/{goal_id}", headers=admin_headers)
