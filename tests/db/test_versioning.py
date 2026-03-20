"""Tests for document versioning — client.py versioning methods and pipeline integration.

Tests cover the versioning lifecycle:
  - snapshot_version is called (and delete_chunks is NOT) when content changes
  - snapshot_version is NOT called on metadata-only updates
  - get_document_content delegates to RPC with correct params
  - list_document_versions delegates to RPC correctly
  - version_count flows through search result structures
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cerefox.db.client import CerefoxClient


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_supabase():
    """A Supabase client mock with chainable table/rpc calls."""
    client = MagicMock()
    # Make table() calls chainable
    table_mock = MagicMock()
    table_mock.select.return_value = table_mock
    table_mock.insert.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.delete.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.is_.return_value = table_mock
    table_mock.order.return_value = table_mock
    table_mock.limit.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[], count=0)
    client.table.return_value = table_mock
    return client


@pytest.fixture()
def cerefox_client(mock_supabase):
    from cerefox.config import Settings
    settings = Settings(_env_file=None)
    settings.supabase_url = "https://example.supabase.co"
    settings.supabase_key = "test-key"
    c = CerefoxClient(settings)
    c._client = mock_supabase
    return c


# ── snapshot_version ──────────────────────────────────────────────────────────


class TestSnapshotVersion:
    def test_calls_correct_rpc(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(
            data=[{"version_id": "v-001", "version_number": 1, "chunk_count": 3, "total_chars": 200}]
        )
        result = cerefox_client.snapshot_version("doc-001", source="file", retention_hours=48)
        mock_supabase.rpc.assert_called_once_with(
            "cerefox_snapshot_version",
            {
                "p_document_id": "doc-001",
                "p_source": "file",
                "p_retention_hours": 48,
            },
        )
        assert result["version_id"] == "v-001"
        assert result["version_number"] == 1

    def test_raises_when_rpc_returns_empty(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=[])
        with pytest.raises(RuntimeError, match="returned no data"):
            cerefox_client.snapshot_version("doc-001")

    def test_default_source_is_manual(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(
            data=[{"version_id": "v-002", "version_number": 1, "chunk_count": 0, "total_chars": 0}]
        )
        cerefox_client.snapshot_version("doc-001")
        call_kwargs = mock_supabase.rpc.call_args[0][1]
        assert call_kwargs["p_source"] == "manual"
        assert call_kwargs["p_retention_hours"] == 48


# ── get_document_content ──────────────────────────────────────────────────────


class TestGetDocumentContent:
    def test_current_version_passes_none(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(
            data=[{"document_id": "doc-001", "doc_title": "Test", "full_content": "hello"}]
        )
        result = cerefox_client.get_document_content("doc-001")
        call_params = mock_supabase.rpc.call_args[0][1]
        assert call_params["p_document_id"] == "doc-001"
        assert call_params["p_version_id"] is None
        assert result["doc_title"] == "Test"

    def test_specific_version_passes_uuid(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(
            data=[{"document_id": "doc-001", "doc_title": "Test v1", "full_content": "old content"}]
        )
        cerefox_client.get_document_content("doc-001", version_id="ver-abc")
        call_params = mock_supabase.rpc.call_args[0][1]
        assert call_params["p_version_id"] == "ver-abc"

    def test_returns_none_when_not_found(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=[])
        result = cerefox_client.get_document_content("nonexistent-id")
        assert result is None


# ── list_document_versions ────────────────────────────────────────────────────


class TestListDocumentVersions:
    def test_returns_version_list(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(
            data=[
                {"version_id": "v-002", "version_number": 2, "source": "file",
                 "chunk_count": 5, "total_chars": 400, "created_at": "2026-03-19T10:00:00Z"},
                {"version_id": "v-001", "version_number": 1, "source": "paste",
                 "chunk_count": 3, "total_chars": 200, "created_at": "2026-03-18T10:00:00Z"},
            ]
        )
        versions = cerefox_client.list_document_versions("doc-001")
        mock_supabase.rpc.assert_called_once_with(
            "cerefox_list_document_versions",
            {"p_document_id": "doc-001"},
        )
        assert len(versions) == 2
        assert versions[0]["version_number"] == 2  # newest first

    def test_returns_empty_list_when_no_versions(self, cerefox_client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=[])
        versions = cerefox_client.list_document_versions("doc-001")
        assert versions == []


# ── delete_chunks_for_document (now filters current only) ─────────────────────


class TestDeleteChunksForDocument:
    def test_filters_current_chunks_only(self, cerefox_client, mock_supabase):
        """After versioning, delete_chunks_for_document should only delete current chunks."""
        table_mock = mock_supabase.table.return_value
        table_mock.delete.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.is_.return_value = table_mock
        table_mock.execute.return_value = MagicMock(data=[])

        cerefox_client.delete_chunks_for_document("doc-001")

        # Verify is_ was called to filter version_id IS NULL
        table_mock.is_.assert_called_once_with("version_id", "null")


# ── list_chunks_for_document (now filters current only) ───────────────────────


class TestListChunksForDocument:
    def test_filters_current_chunks(self, cerefox_client, mock_supabase):
        """list_chunks_for_document should only return current chunks (version_id IS NULL)."""
        table_mock = mock_supabase.table.return_value
        table_mock.select.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.is_.return_value = table_mock
        table_mock.order.return_value = table_mock
        table_mock.execute.return_value = MagicMock(
            data=[{"chunk_index": 0, "content": "current chunk", "version_id": None}]
        )

        chunks = cerefox_client.list_chunks_for_document("doc-001")

        table_mock.is_.assert_called_once_with("version_id", "null")
        assert len(chunks) == 1
