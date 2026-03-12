"""Tests for cerefox.chunking.markdown.chunk_markdown.

Covers: empty input, single-chunk shortcut, heading hierarchy, path tracking,
oversized sections, small-chunk merging, paragraph splitting, preamble
handling, no-overlap guarantee, and edge cases.
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


# ── Single-chunk shortcut for small documents ─────────────────────────────────
#
# Documents whose total length fits within max_chunk_chars are returned as a
# single chunk without any heading-based splitting.  Splitting small docs at
# heading boundaries creates fragments too short to embed meaningfully.


class TestSingleChunkShortcut:
    def test_small_plain_text_is_one_chunk(self) -> None:
        text = "Just some plain text."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].heading_level == 0
        assert chunks[0].heading_path == []
        assert chunks[0].title == ""

    def test_small_doc_with_headings_is_one_chunk(self) -> None:
        """A document with H1 + H2s that fits in one chunk stays as one chunk."""
        text = "# About Me\n\n## Background\n\nI like turtles.\n\n## Interests\n\nRust and Python."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].content == text.strip()

    def test_single_chunk_content_preserves_full_markdown(self) -> None:
        """All heading text and body content must be present in the single chunk."""
        text = "# Title\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "# Title" in chunks[0].content
        assert "## Section A" in chunks[0].content
        assert "Content A." in chunks[0].content
        assert "## Section B" in chunks[0].content
        assert "Content B." in chunks[0].content

    def test_exactly_at_limit_is_one_chunk(self) -> None:
        """A document equal to max_chunk_chars must still be one chunk."""
        text = "x" * 100
        chunks = _chunk(text, max_chunk_chars=100)
        assert len(chunks) == 1

    def test_one_char_over_limit_triggers_splitting(self) -> None:
        """A document one character over max_chunk_chars enters the split path."""
        # Two paragraphs whose combined length exceeds the limit.
        # min_chunk_chars=0 prevents the smaller pieces from being re-merged.
        text = "x" * 60 + "\n\n" + "y" * 60  # 122 chars, two paragraphs
        chunks = _chunk(text, max_chunk_chars=100, min_chunk_chars=0)
        assert len(chunks) > 1
        combined = "\n\n".join(c.content for c in chunks)
        assert "x" * 60 in combined
        assert "y" * 60 in combined

    def test_char_count_correct_for_shortcut_chunk(self) -> None:
        text = "# Title\n\nSmall body."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert chunks[0].char_count == len(chunks[0].content)

    def test_chunk_index_is_zero_for_shortcut(self) -> None:
        text = "# Title\n\nSmall body."
        chunks = _chunk(text)
        assert chunks[0].chunk_index == 0


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


# ── Single heading — small docs use the shortcut ──────────────────────────────
#
# These documents are well under max_chunk_chars so the single-chunk shortcut
# applies.  heading_level is 0, heading_path is [], but content is fully
# preserved (including the heading line).


class TestSingleHeading:
    def test_h1_only_returns_one_chunk_with_content(self) -> None:
        text = "# My Title"
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "# My Title" in chunks[0].content

    def test_h1_with_body_preserved(self) -> None:
        text = "# Hello\n\nSome content here."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "# Hello" in chunks[0].content
        assert "Some content here." in chunks[0].content

    def test_h2_only_returns_one_chunk(self) -> None:
        text = "## Section"
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "## Section" in chunks[0].content

    def test_h3_only_returns_one_chunk(self) -> None:
        text = "### Sub"
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "### Sub" in chunks[0].content

    def test_h4_is_not_a_split_boundary(self) -> None:
        """H4 headings are treated as plain body text, not chunk boundaries."""
        text = "## Section\n\n#### Deep heading\n\nContent."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "#### Deep heading" in chunks[0].content


# ── Heading hierarchy (multi-chunk behaviour) ─────────────────────────────────
#
# These tests verify heading breadcrumb logic.  Documents must exceed
# max_chunk_chars to bypass the single-chunk shortcut; each test passes an
# explicit max_chunk_chars just below the total document length while keeping
# every individual section well below the limit so no paragraph-splitting occurs.


class TestHeadingHierarchy:
    def test_h1_and_h2_produce_two_chunks(self) -> None:
        text = "# Title\n\nIntro.\n\n## Section\n\nContent."  # 38 chars
        chunks = _chunk(text, max_chunk_chars=33)
        assert len(chunks) == 2
        assert chunks[0].heading_level == 1
        assert chunks[1].heading_level == 2

    def test_h2_inherits_h1_in_path(self) -> None:
        text = "# Title\n\n## Section\n\nContent."  # 30 chars
        chunks = _chunk(text, max_chunk_chars=25)
        h2 = chunks[1]
        assert h2.heading_path == ["Title", "Section"]
        assert h2.title == "Section"

    def test_h3_path_includes_all_ancestors(self) -> None:
        text = "# Doc\n\n## Chapter\n\n### Sub\n\nBody."  # 34 chars
        chunks = _chunk(text, max_chunk_chars=30)
        h3 = chunks[-1]
        assert h3.heading_level == 3
        assert h3.heading_path == ["Doc", "Chapter", "Sub"]
        assert h3.title == "Sub"

    def test_two_h2s_under_same_h1_share_parent(self) -> None:
        text = "# Title\n\n## Alpha\n\nContent A.\n\n## Beta\n\nContent B."  # 51 chars
        chunks = _chunk(text, max_chunk_chars=30)
        assert len(chunks) == 3
        alpha = chunks[1]
        beta = chunks[2]
        assert alpha.heading_path == ["Title", "Alpha"]
        assert beta.heading_path == ["Title", "Beta"]

    def test_h1_resets_path(self) -> None:
        """Second H1 clears the path accumulated by the first."""
        text = "# First\n\n## Under First\n\n# Second\n\nContent."  # 44 chars
        chunks = _chunk(text, max_chunk_chars=30)
        last = chunks[-1]
        assert last.heading_level == 1
        assert last.heading_path == ["Second"]

    def test_lower_level_after_higher_resets_correctly(self) -> None:
        """An H2 after an H3 under a different H2 should use the new H2 path."""
        text = "# Root\n\n## A\n\n### A.1\n\nBody.\n\n## B\n\nContent B."  # 47 chars
        chunks = _chunk(text, max_chunk_chars=30)
        b = chunks[-1]
        assert b.heading_path == ["Root", "B"]


# ── Preamble ──────────────────────────────────────────────────────────────────


class TestPreamble:
    def test_preamble_before_first_heading_is_its_own_chunk(self) -> None:
        # This doc is 44 chars — shortcut applies (default max=4000).
        # Preamble + heading fit in one chunk; content must be preserved.
        text = "Intro before any heading.\n\n# Title\n\nContent."
        chunks = _chunk(text)
        assert len(chunks) == 1
        assert "Intro before any heading." in chunks[0].content

    def test_preamble_followed_by_heading_splits_when_large(self) -> None:
        text = "Opening.\n\n## Section\n\nBody."  # 27 chars
        chunks = _chunk(text, max_chunk_chars=22)
        assert chunks[0].heading_level == 0
        assert chunks[1].heading_level == 2

    def test_no_preamble_when_doc_starts_with_heading(self) -> None:
        text = "# Title\n\nContent."  # 18 chars, shortcut → single chunk
        chunks = _chunk(text, max_chunk_chars=13)
        # heading_level=1 preserved even when paragraph-split is triggered
        assert chunks[0].heading_level == 1


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
        chunks = _chunk(text, max_chunk_chars=500)
        for c in chunks:
            assert c.char_count <= 600, f"Chunk too large: {c.char_count}"

    def test_heading_chunks_never_merged_regardless_of_size(self) -> None:
        """min_chunk_chars only affects paragraph-level pieces, never heading sections.

        Both heading sections must become separate chunks even if min_chunk_chars
        is set higher than one of them.
        """
        text = "## Normal\n\nGood amount of content here.\n\n## Tiny\n\nok"  # ~52 chars
        chunks = _chunk(text, max_chunk_chars=30, min_chunk_chars=500)
        titles = [c.title for c in chunks]
        assert "Normal" in titles
        assert "Tiny" in titles

    def test_paragraph_piece_merges_into_previous_when_tiny(self) -> None:
        """Paragraph pieces produced by splitting an oversized section are
        merged into the preceding chunk when they fall below min_chunk_chars."""
        big_body = "word " * 250    # ~1250 chars
        tiny_tail = "fin."           # 4 chars
        text = f"## Section\n\n{big_body}\n\n{tiny_tail}"
        chunks = _chunk(text, max_chunk_chars=700, min_chunk_chars=50)
        for c in chunks:
            assert c.char_count >= 50, f"Chunk too small after merge: {c.char_count!r}"

    def test_tiny_heading_section_is_still_its_own_chunk(self) -> None:
        """A heading section with a tiny body must not be dropped.

        Uses max_chunk_chars=10 to bypass the single-chunk shortcut, then
        verifies the tiny section still exists as its own chunk.
        """
        text = "## Header\n\nhi"  # 13 chars
        chunks = _chunk(text, max_chunk_chars=10, min_chunk_chars=500)
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


# ── No overlap between chunks ─────────────────────────────────────────────────


class TestNoOverlap:
    def test_paragraph_split_produces_no_duplicate_content(self) -> None:
        """When a section is split at paragraph boundaries, no content from
        one chunk should appear at the start of the next chunk."""
        long_para_a = "Alpha " * 200   # ~1200 chars
        long_para_b = "Beta " * 200    # ~1200 chars
        text = f"## Section\n\n{long_para_a}\n\n{long_para_b}"
        chunks = _chunk(text, max_chunk_chars=1500)
        assert len(chunks) >= 2
        tail_of_first = chunks[0].content[-50:]
        assert not chunks[1].content.startswith(tail_of_first)

    def test_heading_chunks_have_no_overlap_prefix(self) -> None:
        """Heading-bounded chunks must start with their own heading, not
        content from the previous chunk."""
        text = "# Doc\n\nPreamble content here.\n\n## Section\n\nSection content."  # 60 chars
        chunks = _chunk(text, max_chunk_chars=35)
        assert len(chunks) == 2
        assert chunks[1].content.startswith("## Section")

    def test_reconstruction_has_no_duplication(self) -> None:
        """Concatenating all chunk content should not produce duplicate lines."""
        long_alpha = "Alpha detail. " * 40   # ~560 chars
        long_beta = "Beta detail. " * 40     # ~520 chars
        text = (
            f"# About\n\nIntro paragraph.\n\n"
            f"## Alpha\n\n{long_alpha}\n\n"
            f"## Beta\n\n{long_beta}"
        )
        chunks = _chunk(text)
        reconstructed = "\n\n".join(c.content for c in chunks)
        assert reconstructed.count("Intro paragraph.") == 1
        assert reconstructed.count("Alpha detail.") == len(long_alpha.split("Alpha detail.")) - 1
        assert reconstructed.count("Beta detail.") == len(long_beta.split("Beta detail.")) - 1


# ── Heading path isolation ────────────────────────────────────────────────────


class TestPathIsolation:
    def test_chunk_heading_path_is_a_copy(self) -> None:
        """Modifying a chunk's heading_path must not affect other chunks."""
        text = "# Root\n\n## A\n\nContent A.\n\n## B\n\nContent B."  # 43 chars
        chunks = _chunk(text, max_chunk_chars=30)
        original_path = list(chunks[1].heading_path)
        chunks[1].heading_path.append("MUTATED")
        assert chunks[2].heading_path != chunks[1].heading_path
        assert chunks[1].heading_path[:len(original_path)] == original_path
