"""Remote inference provider for user-managed OpenAI-compatible servers."""
from typing import Optional
from nova_contracts.llm import ModelCapability
from .openai_compatible_provider import OpenAICompatibleProvider


class RemoteInferenceProvider(OpenAICompatibleProvider):
    """Provider for a user-managed OpenAI-compatible server."""

    def __init__(self, url: str, auth_header: Optional[str] = None):
        extra_headers = {}
        if auth_header:
            extra_headers["Authorization"] = auth_header
        super().__init__(
            base_url=url,
            provider_name="custom",
            capabilities={
                ModelCapability.chat,
                ModelCapability.streaming,
                ModelCapability.embeddings,
            },
            extra_headers=extra_headers,
        )
