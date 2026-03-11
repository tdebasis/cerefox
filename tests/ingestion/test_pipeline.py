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
    client.get_document_project_ids.return_value = []
    client.assign_document_projects.return_value = None
    # By default no metadata keys registered (validation passthrough)
    client.list_metadata_keys.return_value = []
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

    def test_insert_document_has_no_project_id_column(self, pipeline, mock_client) -> None:
        """project_id no longer lives on the document row — it goes through junction table."""
        pipeline.ingest_text("# T\n\nB.", title="T")
        call_kwargs = mock_client.insert_document.call_args[0][0]
        assert "project_id" not in call_kwargs

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

    def test_with_project_name_calls_get_or_create(self, pipeline, mock_client) -> None:
        pipeline.ingest_text("# T\n\nB.", title="T", project_name="research")
        mock_client.get_or_create_project.assert_called_once_with("research")
        mock_client.assign_document_projects.assert_called_once_with("doc-001", ["proj-001"])

    def test_without_project_no_project_lookup(self, pipeline, mock_client) -> None:
        pipeline.ingest_text("# T\n\nB.", title="T")
        mock_client.get_or_create_project.assert_not_called()
        mock_client.assign_document_projects.assert_not_called()

    def test_result_project_ids_set_from_name(self, pipeline, mock_client) -> None:
        result = pipeline.ingest_text("# T\n\nB.", title="T", project_name="work")
        assert result.project_ids == ["proj-001"]

    def test_metadata_passed_to_document(self, pipeline, mock_client) -> None:
        meta = {"tags": "idea"}
        pipeline.ingest_text("# T\n\nB.", title="T", metadata=meta)
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["metadata"] == meta

    def test_empty_text_still_calls_insert(self, pipeline, mock_client, mock_embedder) -> None:
        """Edge case: a document with no parseable chunks should still insert a document row."""
        mock_embedder.embed_batch.return_value = []
        result = pipeline.ingest_text("", title="Empty")
        mock_client.insert_document.assert_called_once()
        assert result.chunk_count == 0


# ── M2M project_ids ───────────────────────────────────────────────────────────


class TestProjectIdsM2M:
    def test_project_ids_list_assigned_via_junction(self, pipeline, mock_client) -> None:
        """project_ids list should be passed to assign_document_projects."""
        pipeline.ingest_text("# T\n\nB.", title="T", project_ids=["pid-1", "pid-2"])
        mock_client.assign_document_projects.assert_called_once_with(
            "doc-001", ["pid-1", "pid-2"]
        )
        mock_client.get_or_create_project.assert_not_called()

    def test_single_project_id_converted_to_list(self, pipeline, mock_client) -> None:
        """project_id (singular) should be wrapped in a list."""
        pipeline.ingest_text("# T\n\nB.", title="T", project_id="single-pid")
        mock_client.assign_document_projects.assert_called_once_with("doc-001", ["single-pid"])

    def test_project_ids_takes_precedence_over_project_id(self, pipeline, mock_client) -> None:
        """project_ids wins when both project_ids and project_id are provided."""
        pipeline.ingest_text(
            "# T\n\nB.", title="T",
            project_ids=["pid-a", "pid-b"],
            project_id="ignored",
        )
        mock_client.assign_document_projects.assert_called_once_with(
            "doc-001", ["pid-a", "pid-b"]
        )

    def test_project_ids_takes_precedence_over_project_name(self, pipeline, mock_client) -> None:
        """project_ids wins when both project_ids and project_name are provided."""
        pipeline.ingest_text(
            "# T\n\nB.", title="T",
            project_ids=["pid-a"],
            project_name="would-create-project",
        )
        mock_client.get_or_create_project.assert_not_called()
        mock_client.assign_document_projects.assert_called_once_with("doc-001", ["pid-a"])

    def test_empty_strings_stripped_from_project_ids(self, pipeline, mock_client) -> None:
        """Empty string values from multi-select should be ignored."""
        pipeline.ingest_text("# T\n\nB.", title="T", project_ids=["", "pid-1", ""])
        mock_client.assign_document_projects.assert_called_once_with("doc-001", ["pid-1"])

    def test_result_project_ids_matches_assigned(self, pipeline, mock_client) -> None:
        result = pipeline.ingest_text("# T\n\nB.", title="T", project_ids=["pid-x", "pid-y"])
        assert result.project_ids == ["pid-x", "pid-y"]

    def test_no_project_ids_result_is_empty_list(self, pipeline, mock_client) -> None:
        result = pipeline.ingest_text("# T\n\nB.", title="T")
        assert result.project_ids == []


# ── Deduplication ─────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_existing_hash_returns_skipped(self, pipeline, mock_client) -> None:
        existing = {
            "id": "doc-existing",
            "title": "Already Here",
            "chunk_count": 5,
            "total_chars": 200,
        }
        mock_client.get_document_by_hash.return_value = existing
        mock_client.get_document_project_ids.return_value = ["proj-abc"]
        result = pipeline.ingest_text("# Already Here\n\nSome text.", title="Already Here")
        assert result.skipped is True
        assert result.document_id == "doc-existing"
        assert result.project_ids == ["proj-abc"]

    def test_skipped_result_does_not_insert(self, pipeline, mock_client) -> None:
        mock_client.get_document_by_hash.return_value = {
            "id": "old-id", "title": "Old", "chunk_count": 1, "total_chars": 10,
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


# ── Metadata validation ────────────────────────────────────────────────────────


class TestMetadataValidation:
    def test_empty_registry_allows_any_key(self, pipeline, mock_client) -> None:
        """If no keys registered, validation is a no-op regardless of strict mode."""
        mock_client.list_metadata_keys.return_value = []
        # metadata_strict is True in test_settings by default
        result = pipeline.ingest_text(
            "# T\n\nB.", title="T", metadata={"anything": "goes"}
        )
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["metadata"] == {"anything": "goes"}

    def test_known_key_passes_strict_mode(self, pipeline, mock_client) -> None:
        mock_client.list_metadata_keys.return_value = [
            {"key": "author"}, {"key": "tags"}
        ]
        result = pipeline.ingest_text("# T\n\nB.", title="T", metadata={"author": "Alice"})
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["metadata"] == {"author": "Alice"}

    def test_unknown_key_raises_in_strict_mode(self, pipeline, mock_client, settings) -> None:
        settings.metadata_strict = True
        mock_client.list_metadata_keys.return_value = [{"key": "author"}]
        with pytest.raises(ValueError, match="Unknown metadata key"):
            pipeline.ingest_text("# T\n\nB.", title="T", metadata={"bad_key": "value"})

    def test_unknown_key_stripped_in_non_strict_mode(
        self, pipeline, mock_client, settings
    ) -> None:
        settings.metadata_strict = False
        mock_client.list_metadata_keys.return_value = [{"key": "author"}]
        pipeline.ingest_text(
            "# T\n\nB.", title="T", metadata={"author": "Bob", "unknown": "stripped"}
        )
        doc_kwargs = mock_client.insert_document.call_args[0][0]
        assert doc_kwargs["metadata"] == {"author": "Bob"}
        assert "unknown" not in doc_kwargs["metadata"]

    def test_no_metadata_skips_validation(self, pipeline, mock_client) -> None:
        pipeline.ingest_text("# T\n\nB.", title="T")
        # list_metadata_keys should NOT be called when no metadata provided
        mock_client.list_metadata_keys.assert_not_called()

    def test_registry_error_falls_through(self, pipeline, mock_client) -> None:
        """If the registry call fails, validation is skipped (non-blocking)."""
        mock_client.list_metadata_keys.side_effect = RuntimeError("DB down")
        # Should not raise — metadata passes through
        result = pipeline.ingest_text(
            "# T\n\nB.", title="T", metadata={"any": "key"}
        )
        assert result.document_id == "doc-001"


# ── ingest_text: project_id kwarg (legacy) ────────────────────────────────────


class TestIngestTextProjectId:
    def test_project_id_direct_uses_junction_table(self, pipeline, mock_client) -> None:
        """Passing project_id UUID directly should bypass get_or_create_project."""
        pipeline.ingest_text("# T\n\nB.", title="T", project_id="uuid-from-ui")
        mock_client.get_or_create_project.assert_not_called()
        mock_client.assign_document_projects.assert_called_once_with(
            "doc-001", ["uuid-from-ui"]
        )

    def test_project_id_takes_precedence_over_name(self, pipeline, mock_client) -> None:
        """project_id wins when both are provided."""
        pipeline.ingest_text("# T\n\nB.", title="T", project_name="work", project_id="direct-id")
        mock_client.get_or_create_project.assert_not_called()
        mock_client.assign_document_projects.assert_called_once_with("doc-001", ["direct-id"])


# ── update_document ────────────────────────────────────────────────────────────


class TestUpdateDocument:
    @pytest.fixture()
    def existing_doc(self) -> dict:
        return {
            "id": "doc-001",
            "title": "Original Title",
            "content_hash": "oldhash",
            "metadata": {"topic": "test"},
            "chunk_count": 2,
            "total_chars": 100,
        }

    def test_happy_path_updates_and_reindexes(
        self, pipeline, mock_client, mock_embedder, existing_doc
    ) -> None:
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = None  # no collision
        mock_client.update_document.return_value = {**existing_doc, "title": "New Title"}
        mock_client.get_document_project_ids.return_value = []
        mock_embedder.embed_batch.return_value = [[0.1] * 768]

        result = pipeline.update_document("doc-001", "# New Title\n\nNew body.", "New Title")

        assert result.document_id == "doc-001"
        assert result.title == "New Title"
        assert not result.skipped
        mock_client.delete_chunks_for_document.assert_called_once_with("doc-001")
        mock_client.update_document.assert_called_once()
        mock_client.insert_chunks.assert_called_once()

    def test_raises_when_document_not_found(self, pipeline, mock_client) -> None:
        mock_client.get_document_by_id.return_value = None
        with pytest.raises(ValueError, match="not found"):
            pipeline.update_document("missing-id", "Content.", "Title")

    def test_raises_on_hash_collision_with_different_doc(
        self, pipeline, mock_client, existing_doc
    ) -> None:
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = {
            "id": "other-doc", "title": "Other Doc"
        }
        with pytest.raises(ValueError, match="already exists"):
            pipeline.update_document("doc-001", "Identical content.", "Title")

    def test_same_doc_hash_collision_is_allowed(
        self, pipeline, mock_client, mock_embedder, existing_doc
    ) -> None:
        """Re-saving identical content to the same document should succeed."""
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = existing_doc
        mock_client.update_document.return_value = existing_doc
        mock_client.get_document_project_ids.return_value = []
        mock_embedder.embed_batch.return_value = [[0.0] * 768]

        result = pipeline.update_document("doc-001", "Same content.", "Original Title")
        assert result.document_id == "doc-001"

    def test_project_ids_none_preserves_existing_assignments(
        self, pipeline, mock_client, mock_embedder, existing_doc
    ) -> None:
        """Not passing project_ids should leave existing project associations unchanged."""
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = None
        mock_client.update_document.return_value = existing_doc
        mock_client.get_document_project_ids.return_value = ["proj-abc"]
        mock_embedder.embed_batch.return_value = [[0.0] * 768]

        result = pipeline.update_document("doc-001", "# T\n\nBody.", "T")

        # assign_document_projects should NOT be called — no new assignment
        mock_client.assign_document_projects.assert_not_called()
        # The result should reflect the current (unchanged) project list
        assert result.project_ids == ["proj-abc"]

    def test_project_ids_empty_list_removes_all_assignments(
        self, pipeline, mock_client, mock_embedder, existing_doc
    ) -> None:
        """Passing project_ids=[] should remove the document from all projects."""
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = None
        mock_client.update_document.return_value = existing_doc
        mock_embedder.embed_batch.return_value = [[0.0] * 768]

        result = pipeline.update_document("doc-001", "# T\n\nBody.", "T", project_ids=[])

        mock_client.assign_document_projects.assert_called_once_with("doc-001", [])
        assert result.project_ids == []

    def test_update_with_project_ids_list(
        self, pipeline, mock_client, mock_embedder, existing_doc
    ) -> None:
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = None
        mock_client.update_document.return_value = existing_doc
        mock_embedder.embed_batch.return_value = [[0.0] * 768]

        result = pipeline.update_document(
            "doc-001", "# T\n\nBody.", "T", project_ids=["pid-1", "pid-2"]
        )
        mock_client.assign_document_projects.assert_called_once_with(
            "doc-001", ["pid-1", "pid-2"]
        )
        assert result.project_ids == ["pid-1", "pid-2"]

    def test_embeddings_computed_before_db_changes(
        self, pipeline, mock_client, mock_embedder, existing_doc
    ) -> None:
        """Embed first so a model failure doesn't corrupt the DB state."""
        mock_client.get_document_by_id.return_value = existing_doc
        mock_client.get_document_by_hash.return_value = None
        mock_embedder.embed_batch.side_effect = RuntimeError("GPU OOM")

        with pytest.raises(RuntimeError, match="GPU OOM"):
            pipeline.update_document("doc-001", "# T\n\nBody.", "T")

        # DB should NOT have been touched
        mock_client.delete_chunks_for_document.assert_not_called()
        mock_client.update_document.assert_not_called()


# ── Client: metadata key methods ──────────────────────────────────────────────


class TestClientMetadataKeys:
    """Unit tests for CerefoxClient metadata key methods."""

    @pytest.fixture()
    def client_with_rpc(self) -> MagicMock:
        """Client mock where rpc() is the single point of control."""
        from cerefox.db.client import CerefoxClient
        from cerefox.config import Settings

        client = CerefoxClient.__new__(CerefoxClient)
        client._settings = Settings(
            supabase_url="http://fake", supabase_key="fake",
            database_url="", metadata_strict=True,
        )
        client._client = None
        # Patch rpc at the instance level
        client.rpc = MagicMock()
        return client

    def test_list_metadata_keys_calls_rpc(self, client_with_rpc) -> None:
        from cerefox.db.client import CerefoxClient
        client_with_rpc.rpc.return_value = [{"key": "author", "label": "Author"}]
        result = client_with_rpc.list_metadata_keys()
        client_with_rpc.rpc.assert_called_once_with("cerefox_list_metadata_keys", {})
        assert result == [{"key": "author", "label": "Author"}]

    def test_upsert_metadata_key_calls_rpc(self, client_with_rpc) -> None:
        client_with_rpc.rpc.return_value = [{"key": "tags", "label": "Tags"}]
        result = client_with_rpc.upsert_metadata_key("tags", label="Tags")
        client_with_rpc.rpc.assert_called_once_with(
            "cerefox_upsert_metadata_key",
            {"p_key": "tags", "p_label": "Tags", "p_description": None},
        )
        assert result["key"] == "tags"

    def test_upsert_raises_on_empty_response(self, client_with_rpc) -> None:
        client_with_rpc.rpc.return_value = []
        with pytest.raises(RuntimeError, match="returned no data"):
            client_with_rpc.upsert_metadata_key("somekey")

    def test_delete_metadata_key_calls_rpc(self, client_with_rpc) -> None:
        client_with_rpc.rpc.return_value = []
        client_with_rpc.delete_metadata_key("author")
        client_with_rpc.rpc.assert_called_once_with(
            "cerefox_delete_metadata_key", {"p_key": "author"}
        )


# ── Client: M2M project assignment ────────────────────────────────────────────


class TestClientProjectAssignment:
    """Unit tests for CerefoxClient M2M project methods."""

    @pytest.fixture()
    def supabase_client(self) -> MagicMock:
        """A mock of the raw supabase Client object."""
        sc = MagicMock()
        # Chain: table().select().eq().execute() → data
        table_mock = MagicMock()
        sc.table.return_value = table_mock
        table_mock.select.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.delete.return_value = table_mock
        table_mock.insert.return_value = table_mock
        table_mock.execute.return_value = MagicMock(data=[])
        return sc

    @pytest.fixture()
    def cerefox_client(self, supabase_client) -> "CerefoxClient":
        from cerefox.db.client import CerefoxClient

        c = CerefoxClient.__new__(CerefoxClient)
        c._settings = MagicMock()
        c._client = supabase_client
        return c

    def test_get_document_project_ids_returns_ids(self, cerefox_client, supabase_client) -> None:
        supabase_client.table.return_value.select.return_value\
            .eq.return_value.execute.return_value = MagicMock(
                data=[{"project_id": "pid-1"}, {"project_id": "pid-2"}]
            )
        result = cerefox_client.get_document_project_ids("doc-001")
        assert result == ["pid-1", "pid-2"]

    def test_get_document_project_ids_empty(self, cerefox_client, supabase_client) -> None:
        supabase_client.table.return_value.select.return_value\
            .eq.return_value.execute.return_value = MagicMock(data=[])
        result = cerefox_client.get_document_project_ids("doc-001")
        assert result == []

    def test_assign_document_projects_inserts_rows(
        self, cerefox_client, supabase_client
    ) -> None:
        table_mock = MagicMock()
        table_mock.delete.return_value = table_mock
        table_mock.insert.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.execute.return_value = MagicMock(data=[])
        supabase_client.table.return_value = table_mock

        cerefox_client.assign_document_projects("doc-001", ["pid-a", "pid-b"])

        # Should delete then insert
        table_mock.delete.assert_called_once()
        table_mock.insert.assert_called_once()
        inserted = table_mock.insert.call_args[0][0]
        assert len(inserted) == 2
        assert {"document_id": "doc-001", "project_id": "pid-a"} in inserted

    def test_assign_document_projects_empty_list_only_deletes(
        self, cerefox_client, supabase_client
    ) -> None:
        table_mock = MagicMock()
        table_mock.delete.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.execute.return_value = MagicMock(data=[])
        supabase_client.table.return_value = table_mock

        cerefox_client.assign_document_projects("doc-001", [])

        table_mock.delete.assert_called_once()
        table_mock.insert.assert_not_called()
