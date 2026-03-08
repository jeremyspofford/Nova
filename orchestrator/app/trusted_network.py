"""Trusted network middleware — stamps request.state with trust info.

Requests from trusted CIDRs (private networks, Tailscale, localhost) bypass
auth and are treated as admin. This lets users run both Tailscale (no login)
and Cloudflare tunnel (login required) simultaneously.
"""
from __future__ import annotations

import logging
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Sequence, Union

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

NetworkType = Union[IPv4Network, IPv6Network]


def parse_cidrs(raw: str) -> list[NetworkType]:
    """Parse comma-separated CIDRs into a list of network objects.

    Silently skips invalid entries and logs a warning.
    Returns an empty list if raw is empty (feature disabled).
    """
    if not raw or not raw.strip():
        return []
    nets: list[NetworkType] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ip_network(part, strict=False))
        except ValueError:
            log.warning("Ignoring invalid CIDR in trusted_networks: %r", part)
    return nets


class TrustedNetworkMiddleware(BaseHTTPMiddleware):
    """Stamp every request with trust status based on client IP."""

    def __init__(self, app, trusted_cidrs: Sequence[NetworkType], proxy_header: str = ""):
        super().__init__(app)
        self.trusted_cidrs = list(trusted_cidrs)
        self.proxy_header = proxy_header.strip() if proxy_header else ""
        if self.trusted_cidrs:
            log.info(
                "Trusted networks enabled: %d CIDRs, proxy_header=%s",
                len(self.trusted_cidrs),
                self.proxy_header or "(none)",
            )

    def _get_client_ip(self, request: Request) -> str:
        """Determine the real client IP.

        If a proxy header is configured, use the leftmost (client) value.
        Otherwise fall back to the direct connection IP.
        """
        if self.proxy_header:
            header_val = request.headers.get(self.proxy_header, "")
            if header_val:
                # X-Forwarded-For can be comma-separated; leftmost is the client
                return header_val.split(",")[0].strip()
        return request.client.host if request.client else "127.0.0.1"

    def _is_trusted(self, ip_str: str) -> bool:
        """Check if an IP falls within any trusted CIDR."""
        if not self.trusted_cidrs:
            return False
        try:
            addr = ip_address(ip_str)
        except ValueError:
            return False
        return any(addr in net for net in self.trusted_cidrs)

    async def dispatch(self, request: Request, call_next) -> Response:
        client_ip = self._get_client_ip(request)
        is_trusted = self._is_trusted(client_ip)
        request.state.is_trusted_network = is_trusted
        request.state.client_ip = client_ip
        return await call_next(request)
