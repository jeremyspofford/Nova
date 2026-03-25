"""Page change detection fetcher — fetches URL, converts HTML to text, detects changes."""
import hashlib
import logging

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


async def fetch_page(feed: dict) -> list[dict]:
    """Fetch a page, convert to text, check if content changed since last hash."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(feed["url"], headers={"User-Agent": "Nova-Intel/1.0"})
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    # Remove script/style tags before text extraction
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)

    content_hash = hashlib.sha256(text.encode()).hexdigest()

    # If hash matches last known, no change
    if content_hash == feed.get("last_hash"):
        return []

    # Content changed — return as a single item
    title = soup.title.string.strip() if soup.title and soup.title.string else feed["name"]
    return [{
        "content_hash": content_hash,
        "title": f"[Updated] {title}",
        "url": feed["url"],
        "body": text[:10000],  # Cap body at 10k chars
        "author": None,
        "score": None,
        "published_at": None,
        "metadata": {"change_detected": True, "body_length": len(text)},
    }]
