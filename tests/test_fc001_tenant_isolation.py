"""FC-001 tenant isolation — prove /engrams/* respects per-tenant scoping.

This is the canary test for the FC-001 memory-merging fix. If tenant_id
isolation regresses, this test fails loudly: tenant B's /context query
returns tenant A's engrams.

Uses direct DB inserts (not /engrams/ingest) so the test doesn't depend
on an LLM being available for decomposition. Sentinel tenant UUIDs and a
content tag keep teardown safely scoped.
"""
from __future__ import annotations

import os
import uuid

import asyncpg
import httpx
import pytest


TENANT_A = str(uuid.UUID(int=0xA5F1_0000_0000_0000_0000_0000_0000_0000))
TENANT_B = str(uuid.UUID(int=0xB5F1_0000_0000_0000_0000_0000_0000_0000))
CONTENT_TAG = "nova-test-fc001"

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_USER = os.getenv("POSTGRES_USER", "nova")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "nova_dev_password")
POSTGRES_DB = os.getenv("POSTGRES_DB", "nova")


async def _cleanup_tenants(conn: asyncpg.Connection) -> None:
    """Delete anything the test created. Run before (in case prior run crashed)
    and after (normal teardown)."""
    for tenant in (TENANT_A, TENANT_B):
        await conn.execute("DELETE FROM engrams WHERE tenant_id = $1::uuid", tenant)
        await conn.execute("DELETE FROM sources WHERE tenant_id = $1::uuid", tenant)
        await conn.execute("DELETE FROM retrieval_log WHERE tenant_id = $1::uuid", tenant)


async def _seed_engram(
    conn: asyncpg.Connection,
    tenant_id: str,
    content: str,
    engram_type: str = "fact",
) -> str:
    """Directly insert a single engram with a pre-computed dummy embedding.

    Uses the same halfvec(768) shape the schema expects — all-zeros works
    for our purposes because the isolation test doesn't rely on cosine
    search matching. The /context call will still surface the engram via
    the recursive CTE in spreading_activation when it's the only candidate."""
    dummy_embedding = "[" + ",".join(["0.01"] * 768) + "]"
    engram_id = await conn.fetchval(
        """
        INSERT INTO engrams (
            type, content, embedding, embedding_model,
            importance, activation, source_type, confidence,
            tenant_id, created_at, updated_at
        ) VALUES (
            $1, $2, CAST($3 AS halfvec), 'test-dummy',
            0.8, 1.0, 'chat', 0.9,
            $4::uuid, NOW(), NOW()
        )
        RETURNING id::text
        """,
        engram_type, content, dummy_embedding, tenant_id,
    )
    return engram_id


@pytest.fixture
async def pg():
    """Direct asyncpg connection for seed + cleanup queries."""
    conn = await asyncpg.connect(
        host=POSTGRES_HOST, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, database=POSTGRES_DB,
    )
    await _cleanup_tenants(conn)
    yield conn
    await _cleanup_tenants(conn)
    await conn.close()


class TestTenantIsolation:
    async def test_activate_respects_tenant(
        self, memory: httpx.AsyncClient, pg: asyncpg.Connection,
    ):
        """POST /activate with tenant B must never surface tenant A engrams."""
        a_id = await _seed_engram(
            pg, TENANT_A, f"[{CONTENT_TAG}] tenant A private data about pangolins",
        )
        b_id = await _seed_engram(
            pg, TENANT_B, f"[{CONTENT_TAG}] tenant B private data about durians",
        )

        # Tenant B's activation query for pangolins (tenant A's topic).
        resp = await memory.post(
            "/api/v1/engrams/activate",
            json={"query": "pangolin", "tenant_id": TENANT_B},
        )
        assert resp.status_code == 200
        result = resp.json()
        surfaced_ids = [e["id"] for e in result.get("engrams", [])]
        assert a_id not in surfaced_ids, \
            f"Tenant A engram ({a_id}) leaked into tenant B activation results"

    async def test_context_query_does_not_cross_tenants(
        self, memory: httpx.AsyncClient, pg: asyncpg.Connection,
    ):
        """POST /context for tenant B should never include tenant A engrams
        in engram_ids, regardless of the query."""
        a_id = await _seed_engram(
            pg, TENANT_A, f"[{CONTENT_TAG}] tenant A private data about pangolins",
        )
        b_id = await _seed_engram(
            pg, TENANT_B, f"[{CONTENT_TAG}] tenant B private data about durians",
        )

        # Tenant B asks a vague query — anything returned must be tenant B.
        resp = await memory.post(
            "/api/v1/engrams/context",
            json={
                "query": "favorite",
                "session_id": f"{CONTENT_TAG}-cross",
                "tenant_id": TENANT_B,
                "depth": "standard",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        engram_ids = data.get("engram_ids", [])
        assert a_id not in engram_ids, \
            f"Tenant A engram ({a_id}) leaked into tenant B context call"

    async def test_mark_used_rejects_cross_tenant(
        self, memory: httpx.AsyncClient, pg: asyncpg.Connection,
    ):
        """/mark-used should silently ignore attempts to mark a retrieval_log
        entry owned by a different tenant (see router._resolve_tenant block)."""
        # Seed a retrieval_log row owned by tenant A
        log_id = await pg.fetchval(
            """
            INSERT INTO retrieval_log (query_text, tenant_id)
            VALUES ($1, $2::uuid)
            RETURNING id::text
            """,
            f"[{CONTENT_TAG}] tenant A retrieval", TENANT_A,
        )
        a_id = await _seed_engram(pg, TENANT_A, f"[{CONTENT_TAG}] tenant A fact")

        # Tenant B tries to mark an engram as used on tenant A's retrieval log
        resp = await memory.post(
            "/api/v1/engrams/mark-used",
            json={
                "retrieval_log_id": log_id,
                "engram_ids_used": [a_id],
                "tenant_id": TENANT_B,
            },
        )
        assert resp.status_code == 200  # silent ignore, not an error

        # Verify engrams_used was NOT set on the tenant-A row
        used = await pg.fetchval(
            "SELECT engrams_used FROM retrieval_log WHERE id = $1::uuid",
            log_id,
        )
        assert used is None, f"Cross-tenant mark-used wrote: {used}"

    async def test_missing_tenant_id_falls_back_to_default_with_warn(
        self, memory: httpx.AsyncClient,
    ):
        """Grace-period behavior: no tenant_id → 200 + WARN in service logs.

        Phase 1-3: grace period active. Phase 4 flips to strict 400 — this
        test should be updated to assert 400 once that lands (see FU-008).
        """
        resp = await memory.post(
            "/api/v1/engrams/context",
            json={"query": f"{CONTENT_TAG}-nope", "session_id": "nova-test-missing-tid"},
        )
        assert resp.status_code == 200
