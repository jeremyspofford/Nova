"""Unit tests for Google OAuth URL generation (FC-003)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.oauth import get_google_auth_url


def test_get_google_auth_url_includes_state():
    """State must be embedded in the Google consent URL for CSRF protection."""
    url = get_google_auth_url("http://localhost:8000/cb", "abc123")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert params.get("state") == ["abc123"], f"state missing or wrong: {params}"


def test_get_google_auth_url_signature_requires_state():
    """The signature should require state — passing only redirect_uri must fail.

    This guards against regressions where a future refactor accidentally
    makes state optional, silently disabling CSRF protection.
    """
    import inspect
    sig = inspect.signature(get_google_auth_url)
    state_param = sig.parameters.get("state")
    assert state_param is not None, "get_google_auth_url must accept a state parameter"
    assert state_param.default is inspect.Parameter.empty, (
        "state must be required (no default) to prevent accidental CSRF disablement"
    )


def test_get_google_auth_url_includes_redirect_uri():
    url = get_google_auth_url("http://localhost:8000/cb", "x")
    params = parse_qs(urlparse(url).query)
    assert params.get("redirect_uri") == ["http://localhost:8000/cb"]
