"""
metadata_echo.py
================
Metadata encoding / echo check for the Nova workspace.

Defines a :class:`Metadata` dataclass, provides helpers to *encode* it
(JSON → UTF-8 → base64) and *decode* it back, then runs a round-trip
echo test that asserts bit-perfect fidelity at every stage.

Encoding pipeline
-----------------
    Metadata  ──►  JSON string  ──►  UTF-8 bytes  ──►  base64 string
                                                              │
    Metadata  ◄──  JSON string  ◄──  UTF-8 bytes  ◄──────────┘

Usage
-----
    python metadata_echo.py          # runs the built-in echo test
    python -m pytest test_metadata_echo.py   # runs the full test suite
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Metadata:
    """Structured metadata payload used for the encoding round-trip check."""

    name: str
    version: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Metadata":
        """Reconstruct a :class:`Metadata` instance from a plain dict."""
        return cls(
            name=data["name"],
            version=data["version"],
            timestamp=data["timestamp"],
            tags=list(data.get("tags", [])),
            extra=dict(data.get("extra", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation (mirrors ``dataclasses.asdict``)."""
        return asdict(self)

    # ------------------------------------------------------------------
    # Equality (field-wise, used by the echo test)
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Metadata):
            return NotImplemented
        return self.to_dict() == other.to_dict()


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def encode(metadata: Metadata) -> str:
    """
    Encode *metadata* to a base64 string.

    Pipeline::

        Metadata → JSON (sorted keys) → UTF-8 bytes → base64 string

    Parameters
    ----------
    metadata:
        The :class:`Metadata` instance to encode.

    Returns
    -------
    str
        URL-safe base64-encoded string (no padding stripped).
    """
    json_str: str = json.dumps(metadata.to_dict(), sort_keys=True)
    utf8_bytes: bytes = json_str.encode("utf-8")
    b64_bytes: bytes = base64.b64encode(utf8_bytes)
    return b64_bytes.decode("ascii")


def decode(encoded: str) -> Metadata:
    """
    Decode a base64 string produced by :func:`encode` back to :class:`Metadata`.

    Pipeline::

        base64 string → UTF-8 bytes → JSON string → Metadata

    Parameters
    ----------
    encoded:
        A base64 string previously returned by :func:`encode`.

    Returns
    -------
    Metadata
        The reconstructed :class:`Metadata` instance.

    Raises
    ------
    ValueError
        If *encoded* is not valid base64 or the decoded JSON does not
        contain the required ``name`` / ``version`` fields.
    KeyError
        If mandatory fields are missing from the decoded JSON payload.
    """
    try:
        utf8_bytes: bytes = base64.b64decode(encoded.encode("ascii"))
    except Exception as exc:
        raise ValueError(f"Invalid base64 payload: {exc}") from exc

    json_str: str = utf8_bytes.decode("utf-8")

    try:
        data: dict[str, Any] = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Decoded bytes are not valid JSON: {exc}") from exc

    return Metadata.from_dict(data)


# ---------------------------------------------------------------------------
# Echo (round-trip) check
# ---------------------------------------------------------------------------

def echo(metadata: Metadata) -> Metadata:
    """
    Encode then immediately decode *metadata* and return the result.

    This is the core "echo" operation: the returned object should be
    field-for-field identical to the input.

    Parameters
    ----------
    metadata:
        The :class:`Metadata` instance to echo.

    Returns
    -------
    Metadata
        A freshly decoded copy of *metadata*.
    """
    return decode(encode(metadata))


def run_echo_test(metadata: Metadata | None = None) -> None:
    """
    Run a self-contained echo test and print a detailed report.

    Parameters
    ----------
    metadata:
        Optional custom :class:`Metadata` to test.  If *None*, a default
        sample payload is used.

    Raises
    ------
    AssertionError
        If any stage of the round-trip check fails.
    """
    if metadata is None:
        metadata = Metadata(
            name="nova-echo-test",
            version="1.0.0",
            timestamp="2024-01-01T00:00:00+00:00",
            tags=["echo", "metadata", "encoding"],
            extra={"workspace": "/workspace", "check": True, "count": 42},
        )

    print("=" * 60)
    print("  Metadata Encoding — Echo / Round-Trip Check")
    print("=" * 60)

    # ── Stage 1: original payload ──────────────────────────────────────
    original_dict = metadata.to_dict()
    print(f"\n[1] Original metadata:")
    for key, value in original_dict.items():
        print(f"      {key}: {value!r}")

    # ── Stage 2: encode ────────────────────────────────────────────────
    encoded = encode(metadata)
    print(f"\n[2] Encoded (base64):")
    print(f"      {encoded}")

    # ── Stage 3: decode ────────────────────────────────────────────────
    decoded = decode(encoded)
    decoded_dict = decoded.to_dict()
    print(f"\n[3] Decoded metadata:")
    for key, value in decoded_dict.items():
        print(f"      {key}: {value!r}")

    # ── Stage 4: field-by-field comparison ────────────────────────────
    print(f"\n[4] Field-by-field comparison:")
    all_ok = True
    all_keys = set(original_dict) | set(decoded_dict)
    for key in sorted(all_keys):
        orig_val = original_dict.get(key)
        dec_val = decoded_dict.get(key)
        match = orig_val == dec_val
        status = "✓" if match else "✗"
        print(f"      {status}  {key}: {orig_val!r}  →  {dec_val!r}")
        if not match:
            all_ok = False

    # ── Stage 5: equality assertion ────────────────────────────────────
    assert metadata == decoded, (
        "Round-trip FAILED: decoded metadata does not equal the original.\n"
        f"  Original : {original_dict}\n"
        f"  Decoded  : {decoded_dict}"
    )

    # ── Stage 6: encoded string stability check ────────────────────────
    encoded_again = encode(decoded)
    assert encoded == encoded_again, (
        "Encoding INSTABILITY: re-encoding the decoded object produced a "
        "different base64 string.\n"
        f"  First  : {encoded}\n"
        f"  Second : {encoded_again}"
    )

    print(f"\n[5] Encoding stability:  ✓  (re-encode matches original)")
    print(f"\n{'=' * 60}")
    print(f"  ALL CHECKS PASSED — round-trip fidelity confirmed.")
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_echo_test()
