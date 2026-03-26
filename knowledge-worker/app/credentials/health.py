import asyncio
import base64
import logging

import httpx

from nova_worker_common.credentials.builtin import BuiltinCredentialProvider

logger = logging.getLogger(__name__)

# Platform checks: source_type -> (api_url, header_name, header_value_template)
# header_value_template uses {token} as the placeholder for the decrypted credential.
PLATFORM_CHECKS = {
    "github_profile": ("https://api.github.com/user", "Authorization", "Bearer {token}"),
    "gitlab_profile": ("https://gitlab.com/api/v4/user", "PRIVATE-TOKEN", "{token}"),
}


async def _retrieve_and_decrypt(
    orch_client,
    provider: BuiltinCredentialProvider,
    cred_id: str,
) -> str | None:
    """Fetch encrypted credential from orchestrator and decrypt it.

    Returns the plaintext token, or None on any failure.
    """
    try:
        resp = await orch_client.get(
            f"/api/v1/knowledge/credentials/{cred_id}/retrieve",
        )
        if resp.status_code != 200:
            logger.warning(
                "Failed to retrieve credential %s for health check: HTTP %s",
                cred_id, resp.status_code,
            )
            return None
        data = resp.json()
        encrypted_bytes = base64.b64decode(data["encrypted_data"])
        tenant_id = data["tenant_id"]
        return provider.decrypt(tenant_id, encrypted_bytes)
    except Exception as e:
        logger.warning("Failed to retrieve/decrypt credential %s: %s", cred_id, e)
        return None


async def _check_platform(api_url: str, header_name: str, header_value: str) -> bool:
    """Make a lightweight authenticated GET to the platform API.

    Returns True if the response is 2xx, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(api_url, headers={header_name: header_value})
        if resp.status_code == 200:
            return True
        logger.warning(
            "Platform health check %s returned HTTP %s — token may be expired or invalid",
            api_url, resp.status_code,
        )
        return False
    except Exception as e:
        logger.warning("Platform health check %s failed: %s", api_url, e)
        return False


async def _report_validation(orch_client, cred_id: str, valid: bool) -> None:
    """POST the validation result to the orchestrator validate endpoint."""
    try:
        await orch_client.post(
            f"/api/v1/knowledge/credentials/{cred_id}/validate",
            json={"valid": valid},
        )
    except Exception as e:
        logger.warning("Failed to report validation for credential %s: %s", cred_id, e)


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
                logger.warning("Failed to fetch credentials: %s", resp.status_code)
                await asyncio.sleep(interval)
                continue

            credentials = resp.json()

            # Fetch sources to know which platform each credential serves
            sources_resp = await orch.get("/api/v1/knowledge/sources")
            sources = sources_resp.json() if sources_resp.status_code == 200 else []

            # Map credential_id -> set of source_types
            cred_to_types: dict[str, set[str]] = {}
            for s in sources:
                cid = s.get("credential_id")
                if cid:
                    cred_to_types.setdefault(cid, set()).add(s.get("source_type", ""))

            for cred in credentials:
                cred_id = cred["id"]
                source_types = cred_to_types.get(cred_id, set())

                # Find the first source_type we have a platform check for
                matched_type = next(
                    (st for st in source_types if st in PLATFORM_CHECKS), None,
                )

                if matched_type:
                    api_url, header_name, header_template = PLATFORM_CHECKS[matched_type]

                    # Retrieve and decrypt the credential
                    token = await _retrieve_and_decrypt(orch, provider, cred_id)
                    if token is None:
                        # Retrieval already logged — report as invalid
                        logger.warning(
                            "Credential %s (type=%s): could not decrypt — marking invalid",
                            cred_id, matched_type,
                        )
                        await _report_validation(orch, cred_id, valid=False)
                        continue

                    # Call the platform API
                    header_value = header_template.format(token=token)
                    valid = await _check_platform(api_url, header_name, header_value)

                    if not valid:
                        logger.warning(
                            "Credential %s (type=%s) failed platform validation — "
                            "token may be expired or revoked",
                            cred_id, matched_type,
                        )

                    await _report_validation(orch, cred_id, valid=valid)

                else:
                    # No known platform check — touch the timestamp to show it's been seen
                    await _report_validation(orch, cred_id, valid=True)

        except Exception as e:
            logger.error("Credential health loop error: %s", e)

        await asyncio.sleep(interval)
