"""Extract and validate links from HTML pages."""
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from nova_worker_common.url_validator import validate_url

_SKIP_SCHEMES = {"javascript", "mailto", "tel", "data", "blob"}


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract all links from HTML, resolve relative URLs, filter invalid/SSRF.

    Returns a deduplicated list of valid http(s) URLs.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue

        # Skip anchors, javascript:, mailto:, etc.
        if href.startswith("#"):
            continue
        parsed_href = urlparse(href)
        if parsed_href.scheme in _SKIP_SCHEMES:
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)

        # Only keep http/https
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue

        # Strip fragment
        clean = absolute.split("#")[0]
        if not clean:
            continue

        # Deduplicate
        if clean in seen:
            continue
        seen.add(clean)

        # SSRF validation
        if validate_url(clean) is not None:
            continue

        links.append(clean)

    return links
