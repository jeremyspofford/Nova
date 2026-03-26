"""Abstract base class for platform-specific content extractors."""
from abc import ABC, abstractmethod


class BaseExtractor(ABC):
    """Base class for platform extractors (GitHub, Notion, etc.)."""

    @staticmethod
    @abstractmethod
    def matches(url: str) -> bool:
        """Return True if this extractor handles the given URL."""
        ...

    @abstractmethod
    async def extract(
        self,
        url: str,
        credential: dict | None = None,
    ) -> list[dict]:
        """Extract structured content items from the given URL.

        Each returned dict should contain at minimum:
            - title: str
            - body: str
            - metadata: dict (url, platform-specific fields)

        Args:
            url: The source URL to extract from.
            credential: Optional decrypted credential dict for authenticated access.

        Returns:
            List of content item dicts.
        """
        ...
