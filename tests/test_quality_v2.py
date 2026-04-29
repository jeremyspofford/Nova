"""Integration tests for AI Quality v2 endpoints — real services, no mocks."""
from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest

ORCHESTRATOR_URL = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "")


async def _trigger_benchmark_get_snapshot_id(client) -> str:
    """Kick off a benchmark just to get a snapshot captured. We don't wait for completion."""
    r = await client.post(
        "/api/v1/quality/benchmarks/run",
        headers={"X-Admin-Secret": ADMIN_SECRET},
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    # Snapshot is captured synchronously before kickoff returns.
    # Read the run row to get the snapshot id.
    list_r = await client.get(
        f"/api/v1/quality/benchmarks/runs?limit=5",
        headers={"X-Admin-Secret": ADMIN_SECRET},
    )
    runs = list_r.json()
    for r in runs:
        if r["id"] == run_id:
            return r["config_snapshot_id"]
    pytest.fail(f"could not find run {run_id} in list response")


@pytest.mark.asyncio
async def test_snapshot_get_returns_404_for_missing():
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    fake_uuid = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.get(
            f"/api/v1/quality/snapshots/{fake_uuid}",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_snapshot_get_real():
    """Trigger a benchmark to capture a snapshot, then GET it."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=30.0) as client:
        snapshot_id = await _trigger_benchmark_get_snapshot_id(client)
        r = await client.get(
            f"/api/v1/quality/snapshots/{snapshot_id}",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == snapshot_id
        assert "config_hash" in body
        assert "config" in body
        assert "captured_at" in body


@pytest.mark.asyncio
async def test_snapshot_diff_self_returns_empty():
    """Diffing a snapshot against itself returns no changed_keys."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=30.0) as client:
        snapshot_id = await _trigger_benchmark_get_snapshot_id(client)
        r = await client.get(
            f"/api/v1/quality/snapshots/diff?from={snapshot_id}&to={snapshot_id}",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["changed_keys"] == []


@pytest.mark.asyncio
async def test_snapshot_diff_404_on_missing():
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    fake1 = str(uuid.uuid4())
    fake2 = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.get(
            f"/api/v1/quality/snapshots/diff?from={fake1}&to={fake2}",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        assert r.status_code == 404
