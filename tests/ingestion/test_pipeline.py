"""Tests for cerefox.ingestion.pipeline.IngestionPipeline.

All tests mock the DB client and embedder — no network calls, no Supabase.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from cerefox.config import Settings
from cerefox.ingestion.pipeline import IngestResult, IngestionPipeline, _hash


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def settings(test_settings: Settings) -> Settings:
    return test_settings


@pytest.fixture()
def mock_client() -> MagicMock:
    client = MagicMock()
    client.get_document_by_hash.return_value = None        # not found by default
    client.insert_document.return_value = {"id": "doc-001", "title": "T"}
    client.insert_chunks.return_value = []
    client.get_or_create_project.return_value = {"id": "proj-001", "name": "work"}
    return client


@pytest.fixture()
def mock_embedder() -> MagicMock:
    emb = MagicMock()
    emb.model_name = "test-embedder"
    emb.embed_batch.return_value = [[0.0] * 768]
    return emb


@pytest.fixture()
def pipeline(mock_client, mock_embedder, settings) -> IngestionPipeline:
    return IngestionPipeline(mock_client, mock_embedder, settings)


# ── _hash helper ──────────────────────────────────────────────────────────────


class TestHash:
    def test_returns_64_hex_chars(self) -> None:
        h = _hash("hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self) -> None:
        assert _hash("same text") == _hash("same text")

    def test_different_text_different_hash(self) -> None:
        assert _hash("text A") != _hash("text B")


# ── Happy path ────────────────────────────────────────────────────────────────


class TestIngestText:
    def test_returns_ingest_result(self, pipeline, mock_client) -> None:
        mock_client.insert_document.return_value = {"id": "doc-001", "title": "My Note"}
        result = pipeline.ingest_text("# My Note\n\nContent.", title="My Note")
        assert isinstance(result, IngestResult)
        assert result.document_id == "doc-001"
        assert result.title == "My Note"
        assert not result.skipped

    def test_insert_document_called_with_hash(self, pipeline, mock_client) -> None:
        text = "# Doc\n\nBody."
        pipeline.ingest_text(text, title="Doc")
        call_kwargs = mock_client.insert_document.call_args[0][0]
        assert call_kwargs["content_hash"] == _hash(text)
        assert call_kwargs["title"] == "Doc"

    def test_insert_document_called_with_source(self, pipeline, mock_client) -> None:
        pipeline.ingest_text("# T\n\nB.", title="T", source="file")
        call_kwargs = mock_client.insert_document.call_args[0][0]
        assert call_kwargs["source"] == "file"

    def test_chunks_are_embedded_and_stored(self, pipeline, mock_client, mock_embedder) -> None:
        text = "# Section\n\nSome content."
        pipeline.ingest_text(text, title="Section")
        mock_embedder.embed_batch.assert_called_once()
        mock_client.insert_chunks.assert_called_once()
        chunk_rows = mock_client.insert_chunks.call_args[0][0]
        assert len(chunk_rows) >= 1
        assert chunk_rows[0]["document_id"] == "doc-001"
        assert chunk_rows[0]["embedder_primary"] == "test-embedder"

    def test_chunk_row_has_required_fields(self, pipeline, mock_client, mock_embedder) -> None:
        text = "# Title\n\nContent body."
        mock_embedder.embed_batch.return_value = [[0.1] * 768]
        pipeline.ingest_text(text, title="Title")
        chunk_row = mock_client.insert_chunks.call_args[0][0][0]
        required = {
            "document_id", "chunk_index", "heading_path", "heading_level",
            "title", "content", "char_count", "embedding_primary", "embedder_primary",
        }
        assert required.issubset(chunk_row.keys())

    def test_result_chunk_count_matches_actual(self, pipeline, mock_client, mock_embedder) -> None:
        # Doc with 3 H2 sections.
        text = "## A\n\nBody A.\n\n## B\n\nBody B.\n\n## C\n\nBody C."
        mock_embedder.embed_batch.return_value = [[0.0] * 768] * 3
        mock_client.insert_document.return_value = {"id": "doc-001", "title": "Doc"}
        result = pipeline.ingest_text(text, title="Doc")
        assert result.chunk_count == 3

    def test_with_project_calls_get_or_create(self, pipeline, mock_client) -> None:
        pipeline.ingest_text("# T\n\nB.", title="T", project_name="research")
        mock_client.get_or_create_project.assert_called_once_with("research")
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["project_id"] == "proj-001"

    def test_without_project_no_project_lookup(self, pipeline, mock_client) -> None:
        pipeline.ingest_text("# T\n\nB.", title="T")
        mock_client.get_or_create_project.assert_not_called()
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["project_id"] is None

    def test_result_project_id_set(self, pipeline, mock_client) -> None:
        result = pipeline.ingest_text("# T\n\nB.", title="T", project_name="work")
        assert result.project_id == "proj-001"

    def test_metadata_passed_to_document(self, pipeline, mock_client) -> None:
        meta = {"tags": ["idea"], "confidence": 0.9}
        pipeline.ingest_text("# T\n\nB.", title="T", metadata=meta)
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["metadata"] == meta

    def test_empty_text_still_calls_insert(self, pipeline, mock_client, mock_embedder) -> None:
        """Edge case: a document with no parseable chunks should still insert a document row."""
        mock_embedder.embed_batch.return_value = []
        result = pipeline.ingest_text("", title="Empty")
        # Document row created even for empty content
        mock_client.insert_document.assert_called_once()
        assert result.chunk_count == 0


# ── Deduplication ─────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_existing_hash_returns_skipped(self, pipeline, mock_client) -> None:
        existing = {
            "id": "doc-existing",
            "title": "Already Here",
            "chunk_count": 5,
            "total_chars": 200,
            "project_id": None,
        }
        mock_client.get_document_by_hash.return_value = existing
        result = pipeline.ingest_text("# Already Here\n\nSome text.", title="Already Here")
        assert result.skipped is True
        assert result.document_id == "doc-existing"

    def test_skipped_result_does_not_insert(self, pipeline, mock_client) -> None:
        mock_client.get_document_by_hash.return_value = {
            "id": "old-id", "title": "Old", "chunk_count": 1, "total_chars": 10, "project_id": None
        }
        pipeline.ingest_text("Duplicate content.", title="Old")
        mock_client.insert_document.assert_not_called()
        mock_client.insert_chunks.assert_not_called()

    def test_different_content_not_deduplicated(self, pipeline, mock_client) -> None:
        mock_client.get_document_by_hash.return_value = None
        result = pipeline.ingest_text("# New Content\n\nUnique.", title="New")
        assert not result.skipped
        mock_client.insert_document.assert_called_once()


# ── ingest_file ───────────────────────────────────────────────────────────────


class TestIngestFile:
    def test_reads_file_and_ingests(self, pipeline, mock_client, tmp_path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("# File Note\n\nContent from file.", encoding="utf-8")
        result = pipeline.ingest_file(str(md_file))
        assert result.title == "note"  # stem of filename
        mock_client.insert_document.assert_called_once()
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["source"] == "file"
        assert "note.md" in doc_kwargs["source_path"]

    def test_custom_title_overrides_stem(self, pipeline, mock_client, tmp_path) -> None:
        md_file = tmp_path / "untitled.md"
        md_file.write_text("# Hello\n\nWorld.", encoding="utf-8")
        pipeline.ingest_file(str(md_file), title="My Custom Title")
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["title"] == "My Custom Title"
