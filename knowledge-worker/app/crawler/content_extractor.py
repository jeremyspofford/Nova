"""Extract readable text and metadata from raw HTML."""
from bs4 import BeautifulSoup

_MAX_TEXT_LENGTH = 50_000
_STRIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "iframe"}


def extract_text(html: str) -> str:
    """Extract main text content from HTML, stripping scripts/styles/nav."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace runs
    cleaned = " ".join(text.split())
    return cleaned[:_MAX_TEXT_LENGTH]


def extract_metadata(html: str) -> dict:
    """Extract page metadata: title, description, og:tags."""
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {}

    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        meta["title"] = title_tag.string.strip()

    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content"):
        meta["description"] = desc["content"].strip()

    for prop in ("og:title", "og:description", "og:image"):
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            meta[prop] = tag["content"].strip()

    # Fall back to og:title if no <title>
    if "title" not in meta and "og:title" in meta:
        meta["title"] = meta["og:title"]

    return meta
