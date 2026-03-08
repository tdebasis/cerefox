"""Tests for cerefox.chunking.markdown.chunk_markdown.

Covers: empty input, heading hierarchy, path tracking, oversized sections,
small-chunk merging, paragraph splitting, preamble handling, and edge cases.
No network calls or external dependencies — pure in-process logic.
"""

from __future__ import annotations

import pytest

from cerefox.chunking.markdown import ChunkData, chunk_markdown

# ── Fixtures / helpers ────────────────────────────────────────────────────────

BIG_PARA = "word " * 1000  # ~5000 chars — exceeds default max_chunk_chars


def _chunk(text: str, **kwargs) -> list[ChunkData]:
    return chunk_markdown(text, **kwargs)


# ── Empty / trivial input ─────────────────────────────────────────────────────


class TestEmptyInput:
    def test_empty_string_returns_empty_list(self) -> None:
        assert _chunk("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert _chunk("   \n\n\t  ") == []

    def test_newlines_only_returns_empty_list(self) -> None:
        assert _chunk("\n\n\n") == []


# ── No headings (preamble / paragraph-only docs) ─────────────────────────────


class TestNoHeadings:
    def test_plain_text_becomes_single_chunk(self) -> None:
        text = "Just some plain text with no headings."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].heading_level == 0
        assert chunks[0].heading_path == []
        assert chunks[0].title == ""

    def test_multiple_paragraphs_no_headings_single_chunk(self) -> None:
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = _chunk(text, max_chunk_chars=4000)
        assert len(chunks) == 1

    def test_oversized_plain_text_splits(self) -> None:
        text = BIG_PARA
        chunks = _chunk(text, max_chunk_chars=2000)
        assert len(chunks) > 1
        for c in chunks:
            assert c.heading_level == 0

    def test_chunk_index_sequential_no_headings(self) -> None:
        text = BIG_PARA
        chunks = _chunk(text, max_chunk_chars=1000)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))


# ── Single heading ────────────────────────────────────────────────────────────


class TestSingleHeading:
    def test_h1_only_no_body(self) -> None:
        text = "# My Title"
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].heading_level == 1
        assert chunks[0].title == "My Title"
        assert chunks[0].heading_path == ["My Title"]
        assert "# My Title" in chunks[0].content

    def test_h1_with_body(self) -> None:
        text = "# Hello\n\nSome content here."
        chunks = _chunk(text)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.heading_level == 1
        assert chunk.title == "Hello"
        assert chunk.heading_path == ["Hello"]
        assert "# Hello" in chunk.content
        assert "Some content here." in chunk.content

    def test_h2_only(self) -> None:
        text = "## Section"
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].heading_level == 2
        assert chunks[0].heading_path == ["Section"]

    def test_h3_only(self) -> None:
        text = "### Sub"
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].heading_level == 3
        assert chunks[0].heading_path == ["Sub"]


# ── Heading hierarchy ─────────────────────────────────────────────────────────


class TestHeadingHierarchy:
    def test_h1_and_h2_produce_two_chunks(self) -> None:
        text = "# Title\n\nIntro.\n\n## Section\n\nContent."
        chunks = _chunk(text)
        assert len(chunks) == 2
        assert chunks[0].heading_level == 1
        assert chunks[1].heading_level == 2

    def test_h2_inherits_h1_in_path(self) -> None:
        text = "# Title\n\n## Section\n\nContent."
        chunks = _chunk(text)
        h2 = chunks[1]
        assert h2.heading_path == ["Title", "Section"]
        assert h2.title == "Section"

    def test_h3_path_includes_all_ancestors(self) -> None:
        text = "# Doc\n\n## Chapter\n\n### Sub\n\nBody."
        chunks = _chunk(text)
        h3 = chunks[-1]
        assert h3.heading_level == 3
        assert h3.heading_path == ["Doc", "Chapter", "Sub"]
        assert h3.title == "Sub"

    def test_two_h2s_under_same_h1_share_parent(self) -> None:
        text = "# Title\n\n## Alpha\n\nContent A.\n\n## Beta\n\nContent B."
        chunks = _chunk(text)
        # Expect: H1, H2-Alpha, H2-Beta
        assert len(chunks) == 3
        alpha = chunks[1]
        beta = chunks[2]
        assert alpha.heading_path == ["Title", "Alpha"]
        assert beta.heading_path == ["Title", "Beta"]

    def test_h1_resets_path(self) -> None:
        """Second H1 clears the path accumulated by the first."""
        text = "# First\n\n## Under First\n\n# Second\n\nContent."
        chunks = _chunk(text)
        last = chunks[-1]
        assert last.heading_level == 1
        assert last.heading_path == ["Second"]

    def test_lower_level_after_higher_resets_correctly(self) -> None:
        """An H2 after an H3 under a different H2 should use the new H2 path."""
        text = "# Root\n\n## A\n\n### A.1\n\nBody.\n\n## B\n\nContent B."
        chunks = _chunk(text)
        b = chunks[-1]
        assert b.heading_path == ["Root", "B"]

    def test_h4_is_not_a_split_boundary(self) -> None:
        """H4 headings are treated as plain body text, not chunk boundaries."""
        text = "## Section\n\n#### Deep heading\n\nContent."
        chunks = _chunk(text)
        # Should be 1 chunk — H4 does not split
        assert len(chunks) == 1
        assert "#### Deep heading" in chunks[0].content


# ── Preamble ──────────────────────────────────────────────────────────────────


class TestPreamble:
    def test_preamble_before_first_heading_is_its_own_chunk(self) -> None:
        text = "Intro before any heading.\n\n# Title\n\nContent."
        chunks = _chunk(text)
        preamble = chunks[0]
        assert preamble.heading_level == 0
        assert preamble.heading_path == []
        assert preamble.title == ""
        assert "Intro before any heading." in preamble.content

    def test_preamble_followed_by_heading(self) -> None:
        text = "Opening.\n\n## Section\n\nBody."
        chunks = _chunk(text)
        assert chunks[0].heading_level == 0
        assert chunks[1].heading_level == 2

    def test_no_preamble_when_doc_starts_with_heading(self) -> None:
        text = "# Title\n\nContent."
        chunks = _chunk(text)
        assert chunks[0].heading_level == 1  # no level-0 preamble chunk


# ── Size management ───────────────────────────────────────────────────────────


class TestSizeManagement:
    def test_oversized_section_produces_multiple_chunks(self) -> None:
        body = "\n\n".join([f"Paragraph {i}: " + "x " * 60 for i in range(20)])
        text = f"## Section\n\n{body}"
        chunks = _chunk(text, max_chunk_chars=500)
        assert len(chunks) > 1

    def test_all_paragraph_chunks_under_max(self) -> None:
        body = "\n\n".join([f"Para {i}: " + "x " * 60 for i in range(20)])
        text = f"## Section\n\n{body}"
        # Allow some slack for overlap text prepended to subsequent chunks.
        chunks = _chunk(text, max_chunk_chars=500, overlap_chars=0)
        for c in chunks:
            assert c.char_count <= 600, f"Chunk too large: {c.char_count}"

    def test_heading_chunks_never_merged_regardless_of_size(self) -> None:
        """Heading boundaries always produce their own chunk, even if tiny.

        min_chunk_chars only applies to paragraph-level pieces produced when
        an oversized section is split; it never merges heading-level chunks.
        """
        text = "## Normal\n\nGood amount of content here.\n\n## Tiny\n\nok"
        chunks = _chunk(text, min_chunk_chars=500)
        # Both heading sections must be kept as separate chunks.
        assert len(chunks) == 2
        titles = [c.title for c in chunks]
        assert "Normal" in titles
        assert "Tiny" in titles

    def test_paragraph_piece_merges_into_previous_when_tiny(self) -> None:
        """Paragraph pieces produced by splitting an oversized section are
        merged into the preceding chunk when they fall below min_chunk_chars."""
        # Build a section that exceeds max_chunk_chars so it gets paragraph-split.
        # The last paragraph is deliberately tiny.
        big_body = "word " * 250    # ~1250 chars
        tiny_tail = "fin."          # 4 chars
        text = f"## Section\n\n{big_body}\n\n{tiny_tail}"
        chunks = _chunk(text, max_chunk_chars=700, min_chunk_chars=50, overlap_chars=0)
        # The 4-char tail should be absorbed into the preceding paragraph chunk.
        for c in chunks:
            assert c.char_count >= 50, f"Chunk too small after merge: {c.char_count!r}"

    def test_tiny_heading_section_is_still_its_own_chunk(self) -> None:
        """Even a heading with a one-word body must not be swallowed."""
        text = "## Header\n\nhi"
        chunks = _chunk(text, min_chunk_chars=500)
        assert len(chunks) == 1
        assert chunks[0].title == "Header"

    def test_char_count_matches_content_length(self) -> None:
        text = "# Title\n\nContent.\n\n## Sub\n\nMore."
        for chunk in _chunk(text):
            assert chunk.char_count == len(chunk.content)

    def test_chunk_indices_are_zero_based_and_sequential(self) -> None:
        text = "# A\n\nContent A.\n\n## B\n\nContent B.\n\n### C\n\nContent C."
        chunks = _chunk(text)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


# ── Overlap ───────────────────────────────────────────────────────────────────


class TestOverlap:
    def test_overlap_prepended_to_continuation_chunk(self) -> None:
        """When a section is split at paragraphs, the second chunk starts with
        text from the tail of the first chunk."""
        long_para_a = "Alpha " * 200   # ~1200 chars
        long_para_b = "Beta " * 200    # ~1200 chars
        text = f"## Section\n\n{long_para_a}\n\n{long_para_b}"
        chunks = _chunk(text, max_chunk_chars=1500, overlap_chars=100)
        assert len(chunks) >= 2
        # Second chunk should start with something from the tail of the first.
        tail_of_first = chunks[0].content[-100:]
        # Overlap is a substring pulled from the first chunk's tail.
        assert any(word in chunks[1].content for word in tail_of_first.split()[:3])

    def test_zero_overlap_produces_no_duplicate_content(self) -> None:
        long_para_a = "Alpha " * 200
        long_para_b = "Beta " * 200
        text = f"## Section\n\n{long_para_a}\n\n{long_para_b}"
        chunks = _chunk(text, max_chunk_chars=1500, overlap_chars=0)
        # With 0 overlap, the content of each chunk should not be identical.
        if len(chunks) >= 2:
            assert chunks[0].content != chunks[1].content


# ── Heading path isolation ────────────────────────────────────────────────────


class TestPathIsolation:
    def test_chunk_heading_path_is_a_copy(self) -> None:
        """Modifying a chunk's heading_path must not affect other chunks."""
        text = "# Root\n\n## A\n\nContent A.\n\n## B\n\nContent B."
        chunks = _chunk(text)
        original_path = list(chunks[1].heading_path)
        chunks[1].heading_path.append("MUTATED")
        assert chunks[2].heading_path != chunks[1].heading_path
        # Restore for sanity
        assert chunks[1].heading_path[:len(original_path)] == original_path
