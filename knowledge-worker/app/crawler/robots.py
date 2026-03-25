"""Robots.txt compliance checker with per-domain caching."""
import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


class RobotsChecker:
    """Caches and checks robots.txt per domain."""

    def __init__(self, override_domains: set[str] | None = None):
        self._cache: dict[str, RobotFileParser | None] = {}
        self._override_domains = override_domains or set()

    async def is_allowed(self, url: str, client, user_agent: str = "Nova") -> bool:
        """Check if URL is crawlable per robots.txt."""
        parsed = urlparse(url)
        domain = parsed.netloc

        # Skip check for user's own domains
        if domain in self._override_domains:
            return True

        if domain not in self._cache:
            await self._fetch_robots(domain, parsed.scheme, client)

        parser = self._cache.get(domain)
        if parser is None:
            return True  # No robots.txt or fetch failed -- allow

        return parser.can_fetch(user_agent, url)

    async def _fetch_robots(self, domain: str, scheme: str, client) -> None:
        """Fetch and parse robots.txt for domain."""
        robots_url = f"{scheme}://{domain}/robots.txt"
        try:
            resp = await client.get(robots_url, timeout=5, follow_redirects=True)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
                self._cache[domain] = parser
            else:
                self._cache[domain] = None
        except Exception:
            logger.debug("Failed to fetch robots.txt for %s", domain)
            self._cache[domain] = None
