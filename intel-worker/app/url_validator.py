"""SSRF prevention — thin wrapper re-exporting from nova-worker-common."""
from nova_worker_common.url_validator import BLOCKED_HOSTS, validate_url

__all__ = ["BLOCKED_HOSTS", "validate_url"]
