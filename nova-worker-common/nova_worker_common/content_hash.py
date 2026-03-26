"""Content deduplication hashing."""
import hashlib


def compute_content_hash(title: str, body: str) -> str:
    """Return the SHA-256 hex digest of ``title + body``."""
    return hashlib.sha256((title + "\0" + body).encode()).hexdigest()
