"""Tests for content hashing."""
from nova_worker_common.content_hash import compute_content_hash


class TestContentHash:
    def test_deterministic(self):
        h1 = compute_content_hash("title", "body")
        h2 = compute_content_hash("title", "body")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = compute_content_hash("title A", "body A")
        h2 = compute_content_hash("title B", "body B")
        assert h1 != h2

    def test_different_title_same_body(self):
        h1 = compute_content_hash("alpha", "same body")
        h2 = compute_content_hash("beta", "same body")
        assert h1 != h2

    def test_same_title_different_body(self):
        h1 = compute_content_hash("same title", "alpha")
        h2 = compute_content_hash("same title", "beta")
        assert h1 != h2

    def test_empty_strings(self):
        h = compute_content_hash("", "")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest length

    def test_returns_hex(self):
        h = compute_content_hash("test", "data")
        int(h, 16)  # should not raise
