"""Heading-aware markdown chunker.

Splits markdown text into chunks based on the H1 > H2 > H3 heading hierarchy.
Each heading section becomes one chunk.  Sections that exceed *max_chunk_chars*
are split at paragraph boundaries.  Sections smaller than *min_chunk_chars* are
merged into the preceding chunk.

No overlaps are added between chunks: each heading section is already
semantically self-contained via its heading breadcrumb, and overlaps cause
duplicate content when chunks are concatenated for document reconstruction.

Headings deeper than H3 (H4–H6) are treated as plain body text — they do not
create chunk boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches H1, H2, or H3 only.  Two capturing groups: the hashes and the heading text.
# Strips optional trailing hashes (e.g. "## Heading ##") via rstrip in _parse_sections.
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# Two or more blank lines separate paragraphs.
_PARAGRAPH_SEP = re.compile(r"\n{2,}")


@dataclass
class ChunkData:
    """A single chunk produced by the markdown chunker."""

    chunk_index: int
    heading_path: list[str]
    heading_level: int  # 0 = no heading (preamble), 1–3 = H1–H3
    title: str          # last element of heading_path, or "" for preamble
    content: str        # full text (includes the heading line for non-preamble chunks)
    char_count: int


def chunk_markdown(
    text: str,
    max_chunk_chars: int = 4000,
    min_chunk_chars: int = 100,
) -> list[ChunkData]:
    """Split *text* into heading-aware chunks.

    Args:
        text: Raw markdown string.
        max_chunk_chars: Maximum characters per chunk before splitting at
            paragraph boundaries.
        min_chunk_chars: Minimum chunk size; chunks smaller than this are
            merged into the preceding chunk.

    Returns:
        Ordered list of :class:`ChunkData` objects, zero-indexed.
    """
    stripped = text.strip()
    if not stripped:
        return []

    sections = _parse_sections(stripped)
    chunks: list[ChunkData] = []
    heading_stack: list[str] = []  # current breadcrumb trail

    for level, heading, body in sections:
        # Maintain the breadcrumb stack.
        # Trim the stack to the parent level and push the new heading.
        if level > 0:
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(heading)
            path = list(heading_stack)
        else:
            path = []

        # Build the full content for this section.
        if level > 0:
            header_line = "#" * level + " " + heading
            content = header_line + ("\n\n" + body if body else "")
        else:
            content = body

        if not content.strip():
            continue

        if len(content) <= max_chunk_chars:
            # Heading boundaries always produce their own chunk — never merged.
            _append_chunk(chunks, content, path, level, heading, force_new=True)
        else:
            # Section too large — split at paragraph boundaries.
            #
            # We split the *body* only (not content) so the heading line is
            # never flushed as a tiny standalone chunk.  The heading is
            # prepended to the first paragraph piece, giving each piece
            # enough context when read in isolation.
            header_prefix = ("#" * level + " " + heading + "\n\n") if level > 0 else ""
            pieces = _split_paragraphs(body, max_chunk_chars)

            for i, raw_piece in enumerate(pieces):
                piece = (header_prefix + raw_piece if i == 0 else raw_piece).strip()
                if not piece:
                    continue
                # The first piece starts a fresh section (force_new=True).
                # Subsequent pieces may be merged into the previous if tiny.
                _append_chunk(
                    chunks, piece, path, level, heading,
                    force_new=(i == 0), min_chunk_chars=min_chunk_chars,
                )

            if not pieces:
                # Body was empty — heading-only content exceeded max (very rare).
                _append_chunk(chunks, content, path, level, heading, force_new=True)

    # Re-number after any merges.
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i

    return chunks


# ── Internal helpers ─────────────────────────────────────────────────────────


def _parse_sections(text: str) -> list[tuple[int, str, str]]:
    """Split *text* into ``(level, heading, body)`` tuples.

    ``level == 0`` represents a preamble — content before the first H1/H2/H3
    heading.  Its heading string is empty.

    Uses ``re.split()`` with capturing groups, which produces a flat list in
    the form ``[preamble, hashes, heading_text, body, hashes, heading_text, body, …]``.
    """
    segments: list[tuple[int, str, str]] = []

    parts = _HEADING_RE.split(text)
    # parts[0] is everything before the first heading match.
    preamble = parts[0].strip()
    if preamble:
        segments.append((0, "", preamble))

    # Remaining parts come in triples: (hashes, heading_text, body).
    for i in range(1, len(parts), 3):
        if i + 2 > len(parts):
            break
        hashes = parts[i]                           # e.g. "##"
        heading_text = parts[i + 1].rstrip("#").strip()
        body = parts[i + 2].strip()
        segments.append((len(hashes), heading_text, body))

    return segments


def _append_chunk(
    chunks: list[ChunkData],
    content: str,
    path: list[str],
    level: int,
    heading: str,
    force_new: bool = True,
    min_chunk_chars: int = 0,
) -> None:
    """Append *content* as a new :class:`ChunkData`.

    When *force_new* is ``False`` and the content is shorter than
    *min_chunk_chars*, it is merged into the previous chunk instead of
    creating a new one.  Heading boundaries always pass ``force_new=True``
    so that every H1/H2/H3 section becomes its own chunk regardless of size.
    Paragraph-level pieces from oversized sections use ``force_new=False``.
    """
    if not force_new and len(content) < min_chunk_chars and chunks:
        prev = chunks[-1]
        prev.content = prev.content + "\n\n" + content
        prev.char_count = len(prev.content)
        return

    title = heading if level > 0 else (path[-1] if path else "")
    chunks.append(
        ChunkData(
            chunk_index=len(chunks),
            heading_path=path,
            heading_level=level,
            title=title,
            content=content,
            char_count=len(content),
        )
    )


def _split_paragraphs(text: str, max_chars: int) -> list[str]:
    """Split *text* at paragraph boundaries, keeping each piece under *max_chars*.

    Consecutive paragraphs are accumulated until adding the next one would
    exceed *max_chars*.  No overlap is added between pieces — the heading
    prefix (prepended by the caller for the first piece) provides sufficient
    context for each chunk when read in isolation.

    If a single paragraph is longer than *max_chars*, it is hard-split by
    character count.
    """
    paragraphs = [p for p in _PARAGRAPH_SEP.split(text) if p.strip()]
    if not paragraphs:
        return []

    result: list[str] = []
    current_parts: list[str] = []
    current_len: int = 0

    for para in paragraphs:
        # +2 accounts for the "\n\n" separator between accumulated paragraphs.
        addition = len(para) + (2 if current_parts else 0)

        if current_len + addition <= max_chars:
            current_parts.append(para)
            current_len += addition
        else:
            if current_parts:
                result.append("\n\n".join(current_parts))
                current_parts = [para]
                current_len = len(para)
            else:
                # A single paragraph exceeds max_chars — hard-split it.
                step = max_chars // 2
                for start in range(0, len(para), step):
                    result.append(para[start: start + max_chars])
                current_parts = []
                current_len = 0

    if current_parts:
        result.append("\n\n".join(current_parts))

    return result
