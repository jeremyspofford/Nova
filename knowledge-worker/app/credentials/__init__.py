"""Credential retrieval for authenticated knowledge source crawling."""
import base64
import logging

from nova_worker_common.credentials.builtin import BuiltinCredentialProvider
from app.config import settings

logger = logging.getLogger(__name__)


async def retrieve_credential(orch_client, credential_id: str) -> str | None:
    """Fetch encrypted credential from orchestrator and decrypt locally.

    Returns the decrypted plaintext token, or None if retrieval/decryption fails.
    Failures are logged but never raised — callers fall back to unauthenticated access.
    """
    if not settings.credential_master_key:
        logger.warning(
            "No CREDENTIAL_MASTER_KEY configured — cannot decrypt credential %s",
            credential_id,
        )
        return None

    try:
        resp = await orch_client.get(
            f"/api/v1/knowledge/credentials/{credential_id}/retrieve",
        )
        if resp.status_code != 200:
            logger.warning(
                "Failed to retrieve credential %s: HTTP %s",
                credential_id, resp.status_code,
            )
            return None

        data = resp.json()
        encrypted_bytes = base64.b64decode(data["encrypted_data"])
        tenant_id = data["tenant_id"]

        provider = BuiltinCredentialProvider(master_key_hex=settings.credential_master_key)
        return provider.decrypt(tenant_id, encrypted_bytes)
    except Exception as e:
        logger.warning("Failed to retrieve credential %s: %s", credential_id, e)
        return None
