import asyncio
import logging

from nova_worker_common.credentials.builtin import BuiltinCredentialProvider

logger = logging.getLogger(__name__)

# Platform-specific health check endpoints
PLATFORM_CHECKS = {
    "github_profile": ("https://api.github.com/user", "Authorization", "Bearer {token}"),
    "gitlab_profile": ("https://gitlab.com/api/v4/user", "PRIVATE-TOKEN", "{token}"),
}


async def run_credential_health_loop(config, get_orch_client):
    """Background loop: validate credentials every 6 hours."""
    await asyncio.sleep(60)  # Initial delay — let services stabilize

    master_key = config.credential_master_key
    if not master_key:
        logger.warning("No CREDENTIAL_MASTER_KEY — credential health checks disabled")
        return

    provider = BuiltinCredentialProvider(master_key_hex=master_key)
    interval = 6 * 3600  # 6 hours

    while True:
        try:
            orch = get_orch_client()

            # Fetch all credentials
            resp = await orch.get("/api/v1/knowledge/credentials")
            if resp.status_code != 200:
                logger.warning(f"Failed to fetch credentials: {resp.status_code}")
                await asyncio.sleep(interval)
                continue

            credentials = resp.json()

            # Fetch sources to know which platform each credential serves
            sources_resp = await orch.get("/api/v1/knowledge/sources")
            sources = sources_resp.json() if sources_resp.status_code == 200 else []

            # Map credential_id -> source_types
            cred_to_types: dict[str, set[str]] = {}
            for s in sources:
                cid = s.get("credential_id")
                if cid:
                    cred_to_types.setdefault(cid, set()).add(s.get("source_type", ""))

            for cred in credentials:
                cred_id = cred["id"]
                source_types = cred_to_types.get(cred_id, set())

                # Try to validate against a known platform
                validated = False
                for stype in source_types:
                    if stype in PLATFORM_CHECKS:
                        try:
                            await orch.post(f"/api/v1/knowledge/credentials/{cred_id}/validate")
                            validated = True
                        except Exception as e:
                            logger.warning(f"Health check failed for credential {cred_id}: {e}")
                        break

                if not validated:
                    # Generic credential — just touch the timestamp
                    try:
                        await orch.post(f"/api/v1/knowledge/credentials/{cred_id}/validate")
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Credential health loop error: {e}")

        await asyncio.sleep(interval)
