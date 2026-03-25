"""Platform-specific content extractors.

Extractors handle structured platforms (GitHub, Notion, etc.) that benefit
from API-based extraction rather than generic HTML crawling.
"""
from .base import BaseExtractor


def get_extractor(url: str) -> BaseExtractor | None:
    """Return a platform extractor for *url*, or None for generic crawling.

    Platform extractors are registered in later tasks (e.g. GitHub, Notion).
    """
    # Stub -- always returns None until platform extractors are added.
    return None
