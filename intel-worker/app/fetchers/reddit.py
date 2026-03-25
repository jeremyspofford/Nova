"""Reddit JSON fetcher — uses old.reddit.com public JSON API."""
import hashlib
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Nova-Intel/1.0 (AI ecosystem monitor)"}


async def fetch_reddit(feed: dict) -> list[dict]:
    """Fetch new posts from a subreddit via JSON API."""
    url = feed["url"]
    if not url.endswith(".json"):
        # Ensure we're hitting the JSON endpoint
        url = url.rstrip("/") + ".json"

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers=_HEADERS, params={"limit": "25", "raw_json": "1"})
        resp.raise_for_status()

    data = resp.json()
    items = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        content_hash = hashlib.sha256(f"{title}{selftext}".encode()).hexdigest()
        created_utc = post.get("created_utc")
        published = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
            if created_utc else None
        )
        items.append({
            "content_hash": content_hash,
            "title": title,
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "body": selftext,
            "author": post.get("author"),
            "score": post.get("score", 0),
            "published_at": published,
            "metadata": {
                "subreddit": post.get("subreddit", ""),
                "num_comments": post.get("num_comments", 0),
                "is_self": post.get("is_self", True),
                "external_url": post.get("url", "") if not post.get("is_self") else None,
            },
        })
    return items
