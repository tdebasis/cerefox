"""Tests for cerefox.backup.fs_backup.FileSystemBackup.

All tests use temporary directories and mocked DB clients.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cerefox.backup.fs_backup import BackupInfo, FileSystemBackup


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_client() -> MagicMock:
    client = MagicMock()
    client.list_documents.return_value = [
        {"id": "doc-1", "title": "Note A", "content_hash": "hash-a", "chunk_count": 2},
        {"id": "doc-2", "title": "Note B", "content_hash": "hash-b", "chunk_count": 1},
    ]
    client.list_chunks_for_document.side_effect = lambda doc_id: {
        "doc-1": [
            {"chunk_index": 0, "content": "chunk 0 of doc 1"},
            {"chunk_index": 1, "content": "chunk 1 of doc 1"},
        ],
        "doc-2": [
            {"chunk_index": 0, "content": "chunk 0 of doc 2"},
        ],
    }.get(doc_id, [])
    client.get_document_by_hash.return_value = None  # not present by default
    client.insert_document.return_value = {"id": "new-doc-id"}
    client.insert_chunks.return_value = []
    return client


@pytest.fixture()
def backup(mock_client, tmp_path) -> FileSystemBackup:
    return FileSystemBackup(mock_client, backup_dir=str(tmp_path / "backups"))


# ── Create ────────────────────────────────────────────────────────────────────


class TestCreate:
    def test_returns_backup_info(self, backup) -> None:
        info = backup.create()
        assert isinstance(info, BackupInfo)
        assert info.document_count == 2
        assert info.chunk_count == 3

    def test_file_exists_after_create(self, backup) -> None:
        info = backup.create()
        assert Path(info.path).exists()

    def test_file_is_valid_json(self, backup) -> None:
        info = backup.create()
        with open(info.path) as f:
            payload = json.load(f)
        assert payload["version"] == 1
        assert payload["document_count"] == 2
        assert payload["chunk_count"] == 3

    def test_documents_embedded_with_chunks(self, backup) -> None:
        info = backup.create()
        with open(info.path) as f:
            payload = json.load(f)
        docs = payload["documents"]
        assert len(docs) == 2
        assert "chunks" in docs[0]
        assert len(docs[0]["chunks"]) == 2

    def test_label_appears_in_filename(self, backup) -> None:
        info = backup.create(label="pre-migration")
        assert "pre-migration" in Path(info.path).name

    def test_backup_dir_created_if_missing(self, mock_client, tmp_path) -> None:
        new_dir = tmp_path / "nested" / "backup_dir"
        b = FileSystemBackup(mock_client, backup_dir=str(new_dir))
        b.create()
        assert new_dir.exists()

    def test_size_bytes_is_nonzero(self, backup) -> None:
        info = backup.create()
        assert info.size_bytes > 0

    def test_empty_knowledge_base(self, mock_client, tmp_path) -> None:
        mock_client.list_documents.return_value = []
        b = FileSystemBackup(mock_client, backup_dir=str(tmp_path))
        info = b.create()
        assert info.document_count == 0
        assert info.chunk_count == 0


# ── Restore ───────────────────────────────────────────────────────────────────


class TestRestore:
    def test_restore_inserts_documents_and_chunks(self, backup, mock_client) -> None:
        info = backup.create()
        # Simulate fresh DB — nothing present
        mock_client.get_document_by_hash.return_value = None
        stats = backup.restore(info.path)
        assert stats["restored"] == 2
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

    def test_restore_skips_existing_documents(self, backup, mock_client) -> None:
        info = backup.create()
        # All docs already present
        mock_client.get_document_by_hash.return_value = {"id": "old-id"}
        stats = backup.restore(info.path)
        assert stats["skipped"] == 2
        assert stats["restored"] == 0

    def test_dry_run_makes_no_inserts(self, backup, mock_client) -> None:
        info = backup.create()
        backup.restore(info.path, dry_run=True)
        mock_client.insert_document.assert_not_called()
        mock_client.insert_chunks.assert_not_called()

    def test_dry_run_returns_correct_stats(self, backup, mock_client) -> None:
        info = backup.create()
        mock_client.get_document_by_hash.return_value = None
        stats = backup.restore(info.path, dry_run=True)
        assert stats["restored"] == 2

    def test_restore_missing_file_raises(self, backup) -> None:
        with pytest.raises(FileNotFoundError):
            backup.restore("/nonexistent/path/backup.json")

    def test_restore_wrong_version_raises(self, backup, tmp_path) -> None:
        bad_backup = tmp_path / "bad.json"
        bad_backup.write_text(json.dumps({"version": 99, "documents": []}))
        with pytest.raises(ValueError, match="Unsupported backup version"):
            backup.restore(str(bad_backup))

    def test_restore_strips_id_before_insert(self, backup, mock_client) -> None:
        """The original 'id' from the backup must not be sent to insert_document,
        since the DB auto-generates a new UUID."""
        info = backup.create()
        mock_client.get_document_by_hash.return_value = None
        backup.restore(info.path)
        for call_args in mock_client.insert_document.call_args_list:
            inserted = call_args[0][0]
            assert "id" not in inserted


# ── List backups ──────────────────────────────────────────────────────────────


class TestListBackups:
    def test_empty_dir_returns_empty_list(self, mock_client, tmp_path) -> None:
        b = FileSystemBackup(mock_client, backup_dir=str(tmp_path / "no-backups"))
        assert b.list_backups() == []

    def test_lists_created_backups(self, backup) -> None:
        backup.create()
        backup.create(label="second")
        listed = backup.list_backups()
        assert len(listed) == 2
        for item in listed:
            assert "path" in item
            assert "size_bytes" in item
            assert item["size_bytes"] > 0

    def test_backups_sorted_by_filename(self, backup) -> None:
        backup.create()
        backup.create()
        listed = backup.list_backups()
        filenames = [item["filename"] for item in listed]
        assert filenames == sorted(filenames)
