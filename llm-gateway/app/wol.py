"""
Wake-on-LAN magic packet sender — stdlib only, no new dependencies.

Sends the standard 102-byte magic packet (6x 0xFF + 16x MAC) via UDP port 9.
Used to wake a remote Ollama host (e.g. Dell PC on LAN) when detected as offline.
"""
from __future__ import annotations

import logging
import socket
import struct
from asyncio import get_running_loop

log = logging.getLogger(__name__)


def _build_magic_packet(mac: str) -> bytes:
    """Build the 102-byte WoL magic packet for a MAC address."""
    mac_clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    mac_bytes = bytes.fromhex(mac_clean)
    return b"\xff" * 6 + mac_bytes * 16


def _send_packet(packet: bytes, broadcast_ip: str) -> bool:
    """Send a magic packet via UDP broadcast. Returns True on success."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (broadcast_ip, 9))
        return True
    except OSError as e:
        log.warning("WoL send failed: %s", e)
        return False


async def send_wol(mac: str, broadcast_ip: str = "255.255.255.255") -> bool:
    """
    Send a Wake-on-LAN packet asynchronously (runs in executor to avoid blocking).
    Returns True if the packet was sent, False on error. Never raises.
    """
    try:
        packet = _build_magic_packet(mac)
        loop = get_running_loop()
        return await loop.run_in_executor(None, _send_packet, packet, broadcast_ip)
    except Exception as e:
        log.warning("WoL error: %s", e)
        return False
