"""Deterministic recursive text splitter.

Sizes are measured in CHARACTERS. Chunks never span pages, so every chunk has an exact page
number for citations. Splitting prefers paragraph, then line, then sentence, then word
boundaries, and carries `overlap` characters of trailing context into the next chunk.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.services.extraction_service import Page

_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]


@dataclass(frozen=True)
class TextChunk:
    index: int
    page_number: int | None
    text: str
    content_hash: str


def _split(text: str, size: int, seps: list[str]) -> list[str]:
    """Split `text` into pieces no longer than `size`, keeping separators attached."""
    if len(text) <= size:
        return [text]
    if not seps:
        return [text[i : i + size] for i in range(0, len(text), size)]
    sep, rest = seps[0], seps[1:]
    parts = text.split(sep)
    pieces: list[str] = []
    for i, part in enumerate(parts):
        piece = part + (sep if i < len(parts) - 1 else "")
        if not piece:
            continue
        if len(piece) > size:
            pieces.extend(_split(piece, size, rest))
        else:
            pieces.append(piece)
    return pieces


def _merge(pieces: list[str], size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > size:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            # Start the next chunk at a word boundary inside the overlap window.
            if tail and not tail[0].isspace():
                cut = re.search(r"\s", tail)
                tail = tail[cut.end():] if cut else ""
            current = tail + piece
            if len(current) > size:  # overlap plus piece would overflow; drop the overlap
                current = piece
        else:
            current += piece
    if current.strip():
        chunks.append(current)
    return chunks


def split_text(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and larger than the overlap")
    return [c.strip() for c in _merge(_split(text, size, _SEPARATORS), size, overlap) if c.strip()]


def chunk_pages(pages: list[Page], size: int, overlap: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in pages:
        for text in split_text(page.text, size, overlap):
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    page_number=page.number,
                    text=text,
                    content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return chunks
