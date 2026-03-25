"""Platform-specific content extractors.

Extractors handle structured platforms (GitHub, Notion, etc.) that benefit
from API-based extraction rather than generic HTML crawling.
"""
from .base import BaseExtractor
from .github import GitHubExtractor

EXTRACTORS = [GitHubExtractor]


def get_extractor(url: str) -> BaseExtractor | None:
    """Return a platform extractor for *url*, or None for generic crawling."""
    for ext_cls in EXTRACTORS:
        if ext_cls.matches(url):
            return ext_cls()
    return None
