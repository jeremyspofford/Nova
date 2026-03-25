"""RSS/Atom feed fetcher using feedparser."""
import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx

log = logging.getLogger(__name__)


async def fetch_rss(feed: dict) -> list[dict]:
    """Fetch and parse an RSS/Atom feed. Returns list of content items."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(feed["url"], headers={"User-Agent": "Nova-Intel/1.0"})
        resp.raise_for_status()

    parsed = feedparser.parse(resp.text)
    items = []
    for entry in parsed.entries[:25]:  # Cap at 25 per fetch
        title = entry.get("title", "")
        body = entry.get("summary", "") or entry.get("description", "")
        content_hash = hashlib.sha256(f"{title}{body}".encode()).hexdigest()
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
        items.append({
            "content_hash": content_hash,
            "title": title,
            "url": entry.get("link", ""),
            "body": body,
            "author": entry.get("author", None),
            "score": None,
            "published_at": published,
            "metadata": {"feed_title": parsed.feed.get("title", "")},
        })
    return items
