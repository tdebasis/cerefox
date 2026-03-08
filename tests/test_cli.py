"""Tests for cerefox.cli — Click command-line interface.

Uses Click's CliRunner so no real Supabase connection is needed.
Embedder and pipeline are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cerefox.cli import cli
from cerefox.ingestion.pipeline import IngestResult


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _make_pipeline_mock(result: IngestResult | None = None) -> MagicMock:
    """Return a mock IngestionPipeline that returns a preset IngestResult."""
    mock = MagicMock()
    default_result = result or IngestResult(
        document_id="doc-abc",
        title="Test Note",
        chunk_count=3,
        total_chars=500,
        skipped=False,
    )
    mock.ingest_text.return_value = default_result
    mock.ingest_file.return_value = default_result
    return mock


def _make_client_mock() -> MagicMock:
    client = MagicMock()
    client.list_documents.return_value = [
        {"id": "doc-1", "title": "Alpha", "chunk_count": 2, "total_chars": 300},
        {"id": "doc-2", "title": "Beta", "chunk_count": 1, "total_chars": 150},
    ]
    client.list_projects.return_value = [
        {"id": "proj-1", "name": "Personal"},
        {"id": "proj-2", "name": "Work"},
    ]
    return client


# ── ingest (paste mode) ───────────────────────────────────────────────────────


class TestIngestPaste:
    def test_paste_requires_title(self, runner) -> None:
        result = runner.invoke(cli, ["ingest", "--paste"])
        assert result.exit_code != 0
        assert "--title" in result.output

    def test_paste_ingests_stdin(self, runner, tmp_path) -> None:
        pipeline_mock = _make_pipeline_mock()
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=MagicMock()),
            patch("cerefox.cli._get_embedder", return_value=MagicMock()),
            patch("cerefox.ingestion.pipeline.IngestionPipeline", return_value=pipeline_mock),
        ):
            result = runner.invoke(
                cli,
                ["ingest", "--paste", "--title", "My Thought"],
                input="# My Thought\n\nSome content.",
            )
        assert result.exit_code == 0
        assert "Ingested" in result.output

    def test_paste_shows_skipped_message(self, runner) -> None:
        skipped = IngestResult("old-id", "Old", 2, 100, skipped=True)
        pipeline_mock = _make_pipeline_mock(result=skipped)
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=MagicMock()),
            patch("cerefox.cli._get_embedder", return_value=MagicMock()),
            patch("cerefox.ingestion.pipeline.IngestionPipeline", return_value=pipeline_mock),
        ):
            result = runner.invoke(
                cli,
                ["ingest", "--paste", "--title", "Old"],
                input="Duplicate content.",
            )
        assert result.exit_code == 0
        assert "Skipped" in result.output


# ── ingest (file mode) ────────────────────────────────────────────────────────


class TestIngestFile:
    def test_file_ingestion(self, runner, tmp_path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("# Note\n\nContent.", encoding="utf-8")

        pipeline_mock = _make_pipeline_mock()
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=MagicMock()),
            patch("cerefox.cli._get_embedder", return_value=MagicMock()),
            patch("cerefox.ingestion.pipeline.IngestionPipeline", return_value=pipeline_mock),
        ):
            result = runner.invoke(cli, ["ingest", str(md_file)])
        assert result.exit_code == 0
        assert "Ingested" in result.output

    def test_nonexistent_file_fails(self, runner) -> None:
        result = runner.invoke(cli, ["ingest", "/nonexistent/file.md"])
        assert result.exit_code != 0

    def test_no_path_and_no_paste_fails(self, runner) -> None:
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=MagicMock()),
            patch("cerefox.cli._get_embedder", return_value=MagicMock()),
        ):
            result = runner.invoke(cli, ["ingest"])
        assert result.exit_code != 0

    def test_invalid_metadata_json_fails(self, runner, tmp_path) -> None:
        md_file = tmp_path / "note.md"
        md_file.write_text("# T\n\nB.", encoding="utf-8")
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=MagicMock()),
            patch("cerefox.cli._get_embedder", return_value=MagicMock()),
        ):
            result = runner.invoke(cli, ["ingest", str(md_file), "--metadata", "not-json"])
        assert result.exit_code != 0
        assert "JSON" in result.output


# ── list-docs ─────────────────────────────────────────────────────────────────


class TestListDocs:
    def test_shows_document_list(self, runner) -> None:
        client_mock = _make_client_mock()
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=client_mock),
        ):
            result = runner.invoke(cli, ["list-docs"])
        assert result.exit_code == 0
        assert "Alpha" in result.output
        assert "Beta" in result.output

    def test_empty_list_shows_message(self, runner) -> None:
        client_mock = MagicMock()
        client_mock.list_documents.return_value = []
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=client_mock),
        ):
            result = runner.invoke(cli, ["list-docs"])
        assert result.exit_code == 0
        assert "No documents" in result.output


# ── delete-doc ────────────────────────────────────────────────────────────────


class TestDeleteDoc:
    def test_delete_with_yes_flag(self, runner) -> None:
        client_mock = _make_client_mock()
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=client_mock),
        ):
            result = runner.invoke(cli, ["delete-doc", "doc-1", "--yes"])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        client_mock.delete_document.assert_called_once_with("doc-1")

    def test_delete_aborted_on_no(self, runner) -> None:
        client_mock = _make_client_mock()
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=client_mock),
        ):
            result = runner.invoke(cli, ["delete-doc", "doc-1"], input="n\n")
        # Aborted — delete should not be called
        client_mock.delete_document.assert_not_called()


# ── list-projects ─────────────────────────────────────────────────────────────


class TestListProjects:
    def test_shows_projects(self, runner) -> None:
        client_mock = _make_client_mock()
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=client_mock),
        ):
            result = runner.invoke(cli, ["list-projects"])
        assert result.exit_code == 0
        assert "Personal" in result.output
        assert "Work" in result.output

    def test_empty_projects_shows_message(self, runner) -> None:
        client_mock = MagicMock()
        client_mock.list_projects.return_value = []
        with (
            patch("cerefox.cli.Settings"),
            patch("cerefox.cli._get_client", return_value=client_mock),
        ):
            result = runner.invoke(cli, ["list-projects"])
        assert result.exit_code == 0
        assert "No projects" in result.output
