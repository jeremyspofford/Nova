"""
Markdown-aware text chunking.

Strategy:
1. Split on ## headings (each section is a chunk candidate)
2. If a section exceeds MAX_CHUNK_CHARS, split on paragraph breaks (\\n\\n)
3. If still too long, hard-split at MAX_CHUNK_CHARS with OVERLAP_CHARS overlap
4. Prepend parent heading to each sub-chunk for context
"""
from __future__ import annotations

import re

MAX_CHUNK_CHARS = 500
OVERLAP_CHARS = 100

_HEADING_RE = re.compile(r"^## .+", re.MULTILINE)


def chunk_markdown(text: str, source_file: str | None = None) -> list[str]:
    """Split markdown text into chunks, preserving heading context."""
    sections = _split_on_headings(text)
    chunks: list[str] = []
    for heading, body in sections:
        section_text = f"{heading}\n{body}".strip() if heading else body.strip()
        if not section_text:
            continue
        if len(section_text) <= MAX_CHUNK_CHARS:
            chunks.append(section_text)
        else:
            chunks.extend(_split_section(heading, body))
    return chunks


def _split_on_headings(text: str) -> list[tuple[str | None, str]]:
    """Split text into (heading, body) pairs. Content before the first heading
    gets heading=None."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(None, text)]

    sections: list[tuple[str | None, str]] = []

    # Content before first heading
    if matches[0].start() > 0:
        sections.append((None, text[: matches[0].start()]))

    for i, m in enumerate(matches):
        heading = m.group()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((heading, text[start:end]))

    return sections


def _split_section(heading: str | None, body: str) -> list[str]:
    """Split an oversized section into smaller chunks."""
    prefix = f"{heading}\n" if heading else ""
    paragraphs = body.split("\n\n")
    chunks: list[str] = []
    current = prefix

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        candidate = f"{current}\n\n{para}".strip() if current.strip() != prefix.strip() else f"{prefix}{para}".strip()
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
        else:
            # Flush current if it has content beyond the prefix
            if current.strip() and current.strip() != prefix.strip():
                chunks.append(current.strip())
            # If this single paragraph is too long, hard-split it
            if len(f"{prefix}{para}") > MAX_CHUNK_CHARS:
                chunks.extend(_hard_split(prefix, para))
                current = prefix
            else:
                current = f"{prefix}{para}".strip()

    if current.strip() and current.strip() != prefix.strip():
        chunks.append(current.strip())

    return chunks


def _hard_split(prefix: str, text: str) -> list[str]:
    """Hard-split text at MAX_CHUNK_CHARS with OVERLAP_CHARS overlap,
    prepending prefix to each chunk."""
    chunks: list[str] = []
    max_body = MAX_CHUNK_CHARS - len(prefix)
    if max_body <= 0:
        max_body = MAX_CHUNK_CHARS

    pos = 0
    while pos < len(text):
        end = pos + max_body
        chunk_body = text[pos:end]
        chunks.append(f"{prefix}{chunk_body}".strip())
        pos = end - OVERLAP_CHARS if end < len(text) else end

    return chunks
