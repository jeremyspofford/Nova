"""Feed fetcher dispatch — implemented in Task 8."""


async def fetch_feed(feed: dict) -> list[dict]:
    """Dispatch to type-specific fetcher. Returns list of content items."""
    raise NotImplementedError(f"Fetcher for {feed.get('feed_type')} not yet implemented")
