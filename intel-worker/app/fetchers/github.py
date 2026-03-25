"""GitHub fetchers — trending repos and release tracking."""
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Nova-Intel/1.0"}
_AI_KEYWORDS = {"ai", "llm", "gpt", "transformer", "neural", "ml", "deep-learning",
                "machine-learning", "langchain", "agent", "rag", "embedding", "diffusion",
                "mcp", "anthropic", "openai", "gemini", "ollama", "vllm"}


async def fetch_github_trending(feed: dict) -> list[dict]:
    """Scrape GitHub trending page for AI/ML repos."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(feed["url"], headers=_HEADERS)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    items = []
    for article in soup.select("article.Box-row")[:30]:
        name_el = article.select_one("h2 a")
        if not name_el:
            continue
        repo_path = name_el.get("href", "").strip("/")
        desc_el = article.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        # Filter to AI/ML repos by keyword match
        combined = f"{repo_path} {description}".lower()
        if not any(kw in combined for kw in _AI_KEYWORDS):
            continue

        content_hash = hashlib.sha256(f"github-trending:{repo_path}".encode()).hexdigest()
        items.append({
            "content_hash": content_hash,
            "title": repo_path,
            "url": f"https://github.com/{repo_path}",
            "body": description,
            "author": repo_path.split("/")[0] if "/" in repo_path else None,
            "score": None,
            "published_at": None,
            "metadata": {"source": "github_trending"},
        })
    return items


async def fetch_github_releases(feed: dict) -> list[dict]:
    """Fetch releases from a GitHub repo's Atom feed."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(feed["url"], headers=_HEADERS)
        resp.raise_for_status()

    import feedparser
    parsed = feedparser.parse(resp.text)
    items = []
    for entry in parsed.entries[:5]:
        title = entry.get("title", "")
        body = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
        content_hash = hashlib.sha256(f"release:{title}".encode()).hexdigest()
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
            "body": body[:5000],
            "author": None,
            "score": None,
            "published_at": published,
            "metadata": {"source": "github_releases"},
        })
    return items
