"""
ModelProvider abstract base class — the swappability contract.
Any LLM backend implementing these three methods works with Nova.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from nova_contracts import (
    CompleteRequest,
    CompleteResponse,
    EmbedRequest,
    EmbedResponse,
    ModelCapability,
    ModelInfo,
    StreamChunk,
)


class ModelProvider(ABC):
    """
    Abstract base for all LLM providers.
    Implementations: LiteLLMProvider, OllamaProvider, FallbackProvider.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'litellm', 'ollama', 'anthropic')."""

    @property
    @abstractmethod
    def capabilities(self) -> set[ModelCapability]:
        """Capabilities this provider supports — used for routing decisions."""

    @abstractmethod
    async def complete(self, request: CompleteRequest) -> CompleteResponse:
        """Non-streaming completion."""

    @abstractmethod
    async def stream(self, request: CompleteRequest) -> AsyncIterator[StreamChunk]:
        """Streaming completion — yields chunks until finish_reason is set."""

    @abstractmethod
    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        """Generate embeddings for a list of texts."""

    def supports(self, capability: ModelCapability) -> bool:
        return capability in self.capabilities
