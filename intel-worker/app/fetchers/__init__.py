"""Feed fetcher dispatch — routes to type-specific fetchers."""
from app.fetchers.github import fetch_github_releases, fetch_github_trending
from app.fetchers.page import fetch_page
from app.fetchers.reddit import fetch_reddit
from app.fetchers.rss import fetch_rss

FETCHERS = {
    "rss": fetch_rss,
    "reddit_json": fetch_reddit,
    "page": fetch_page,
    "github_trending": fetch_github_trending,
    "github_releases": fetch_github_releases,
}


async def fetch_feed(feed: dict) -> list[dict]:
    """Dispatch to the correct fetcher based on feed_type."""
    fetcher = FETCHERS.get(feed.get("feed_type", ""))
    if not fetcher:
        raise ValueError(f"Unknown feed type: {feed.get('feed_type')}")
    return await fetcher(feed)
