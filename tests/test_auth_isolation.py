"""FC-005: admin secret must not authenticate user-context endpoints.

The X-Admin-Secret header is for AdminDep endpoints only. UserDep endpoints
must require a JWT — admin secret should never grant user-impersonation.

The negative case (admin secret rejected on UserDep) is tested as a unit
test in orchestrator/tests/test_auth.py because integration tests from
localhost trigger the trusted-network bypass (returns synthetic admin
regardless of credentials), which masks the admin-secret code path.

This file holds only the positive smoke check: AdminDep endpoints still
work via admin secret.
"""
from __future__ import annotations

import os

import httpx
import pytest

ORCHESTRATOR_URL = os.getenv("NOVA_ORCHESTRATOR_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("NOVA_ADMIN_SECRET", "")


@pytest.mark.asyncio
async def test_admin_secret_accepted_on_admin_endpoint():
    """A request with X-Admin-Secret must still authenticate AdminDep endpoints."""
    if not ADMIN_SECRET:
        pytest.skip("NOVA_ADMIN_SECRET not set")
    async with httpx.AsyncClient(base_url=ORCHESTRATOR_URL, timeout=10.0) as client:
        r = await client.post(
            "/api/v1/knowledge/crawl-log",
            headers={"X-Admin-Secret": ADMIN_SECRET},
            json={
                "source_id": "00000000-0000-0000-0000-000000000000",
                "status": "success",
                "items_found": 0,
                "items_added": 0,
            },
        )
        # Either 201 (created) or 4xx for invalid source_id, but never 401/403.
        assert r.status_code not in (401, 403), (
            f"AdminDep endpoint must accept admin secret; got {r.status_code}: {r.text[:200]}"
        )
