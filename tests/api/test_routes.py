"""Tests for the Cerefox web UI routes.

Uses FastAPI's TestClient with dependency overrides to avoid real DB/embedder calls.
All tests are synchronous and hit no external services.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cerefox.api.app import create_app
from cerefox.api.routes import get_client, get_embedder, get_settings
from cerefox.config import Settings
from cerefox.retrieval.search import SearchResponse, SearchResult


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _mock_settings() -> Settings:
    return Settings(supabase_url="http://fake", supabase_key="fake-key")


def _make_doc(**kwargs) -> dict:
    defaults = {
        "id": "doc-uuid-1",
        "title": "Test Document",
        "source": "file",
        "source_path": "test.md",
        "project_id": None,
        "metadata": {},
        "chunk_count": 3,
        "total_chars": 1500,
        "created_at": "2026-03-08T10:00:00Z",
    }
    return {**defaults, **kwargs}


def _make_project(**kwargs) -> dict:
    defaults = {"id": "proj-uuid-1", "name": "My Project", "description": "Test project"}
    return {**defaults, **kwargs}


def _make_chunk(**kwargs) -> dict:
    defaults = {
        "id": "chunk-uuid-1",
        "document_id": "doc-uuid-1",
        "chunk_index": 0,
        "heading_path": ["Test Document", "Section"],
        "heading_level": 2,
        "title": "Section",
        "content": "Some content here.",
        "char_count": 18,
        "embedder_primary": "mpnet",
        "created_at": "2026-03-08T10:00:00Z",
    }
    return {**defaults, **kwargs}


def _make_search_result(**kwargs) -> SearchResult:
    defaults = {
        "chunk_id": "chunk-uuid-1",
        "document_id": "doc-uuid-1",
        "chunk_index": 0,
        "title": "Section",
        "content": "Relevant content from the knowledge base.",
        "heading_path": ["Doc", "Section"],
        "heading_level": 2,
        "score": 0.87,
        "doc_title": "Test Document",
        "doc_source": "file",
        "doc_project_id": None,
        "doc_metadata": {},
    }
    return SearchResult(**{**defaults, **kwargs})


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.list_documents.return_value = [_make_doc()]
    client.list_projects.return_value = [_make_project()]
    client.count_documents.return_value = 42
    client.reconstruct_doc.return_value = {
        "document_id": "doc-uuid-1",
        "doc_title": "Test Document",
        "doc_source": "file",
        "doc_metadata": {},
        "full_content": "# Test Document\n\nContent.",
        "chunk_count": 3,
        "total_chars": 1500,
    }
    client.list_chunks_for_document.return_value = [_make_chunk()]
    return client


@pytest.fixture()
def mock_embedder():
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 768
    embedder.embed_batch.return_value = [[0.1] * 768]
    return embedder


@pytest.fixture()
def test_client(mock_client, mock_embedder):
    """TestClient with mocked dependencies."""
    app = create_app()
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_client] = lambda: mock_client
    app.dependency_overrides[get_embedder] = lambda: mock_embedder
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def test_client_no_embedder(mock_client):
    """TestClient with no embedder (embedder not installed scenario)."""
    app = create_app()
    app.dependency_overrides[get_settings] = _mock_settings
    app.dependency_overrides[get_client] = lambda: mock_client
    app.dependency_overrides[get_embedder] = lambda: None
    return TestClient(app, raise_server_exceptions=True)


# ── Dashboard ─────────────────────────────────────────────────────────────────


class TestDashboard:
    def test_returns_200(self, test_client, mock_client):
        resp = test_client.get("/")
        assert resp.status_code == 200

    def test_shows_document_count(self, test_client, mock_client):
        mock_client.count_documents.return_value = 42
        resp = test_client.get("/")
        assert "42" in resp.text

    def test_shows_recent_docs(self, test_client, mock_client):
        resp = test_client.get("/")
        assert "Test Document" in resp.text

    def test_shows_projects(self, test_client, mock_client):
        resp = test_client.get("/")
        assert "My Project" in resp.text

    def test_handles_client_error_gracefully(self, test_client, mock_client):
        mock_client.list_documents.side_effect = RuntimeError("DB connection failed")
        resp = test_client.get("/")
        assert resp.status_code == 200
        assert "DB connection failed" in resp.text

    def test_empty_dashboard_shows_ingest_link(self, test_client, mock_client):
        mock_client.list_documents.return_value = []
        mock_client.list_projects.return_value = []
        mock_client.count_documents.return_value = 0
        resp = test_client.get("/")
        assert "ingest" in resp.text.lower()


# ── Search / browser ──────────────────────────────────────────────────────────


class TestSearchPage:
    def test_empty_search_returns_200(self, test_client):
        resp = test_client.get("/search")
        assert resp.status_code == 200

    def test_search_form_is_present(self, test_client):
        resp = test_client.get("/search")
        assert "<form" in resp.text
        assert 'name="q"' in resp.text

    def test_search_with_query_calls_hybrid(self, test_client, mock_client, mock_embedder):
        search_resp = SearchResponse(
            results=[_make_search_result()],
            query="my query",
            mode="hybrid",
            total_found=1,
            response_bytes=100,
            truncated=False,
            metadata={},
        )
        with patch("cerefox.api.routes.SearchClient") as MockSC:
            MockSC.return_value.hybrid.return_value = search_resp
            resp = test_client.get("/search?q=my+query")
        assert resp.status_code == 200
        assert "Test Document" in resp.text

    def test_fts_mode_calls_fts(self, test_client, mock_client):
        search_resp = SearchResponse(
            results=[_make_search_result()],
            query="keyword",
            mode="fts",
            total_found=1,
            response_bytes=100,
            truncated=False,
            metadata={},
        )
        with patch("cerefox.api.routes.SearchClient") as MockSC:
            MockSC.return_value.fts.return_value = search_resp
            resp = test_client.get("/search?q=keyword&mode=fts")
        assert resp.status_code == 200

    def test_semantic_mode_without_embedder_shows_error(self, test_client_no_embedder):
        resp = test_client_no_embedder.get("/search?q=test&mode=semantic")
        assert resp.status_code == 200
        assert "Embedder" in resp.text or "embedder" in resp.text.lower()

    def test_htmx_search_returns_partial(self, test_client, mock_client):
        search_resp = SearchResponse(
            results=[_make_search_result()],
            query="test",
            mode="hybrid",
            total_found=1,
            response_bytes=100,
            truncated=False,
            metadata={},
        )
        with patch("cerefox.api.routes.SearchClient") as MockSC:
            MockSC.return_value.hybrid.return_value = search_resp
            resp = test_client.get(
                "/search?q=test",
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        # Partial should NOT contain full page chrome
        assert "<nav" not in resp.text

    def test_search_shows_empty_state_when_no_results(self, test_client, mock_client):
        search_resp = SearchResponse(
            results=[],
            query="nothing",
            mode="hybrid",
            total_found=0,
            response_bytes=0,
            truncated=False,
            metadata={},
        )
        with patch("cerefox.api.routes.SearchClient") as MockSC:
            MockSC.return_value.hybrid.return_value = search_resp
            resp = test_client.get("/search?q=nothing")
        assert resp.status_code == 200
        assert "No results" in resp.text


# ── Document viewer ───────────────────────────────────────────────────────────


class TestDocumentView:
    def test_returns_200_for_existing_doc(self, test_client, mock_client):
        resp = test_client.get("/document/doc-uuid-1")
        assert resp.status_code == 200

    def test_shows_document_title(self, test_client, mock_client):
        resp = test_client.get("/document/doc-uuid-1")
        assert "Test Document" in resp.text

    def test_shows_chunk_content(self, test_client, mock_client):
        resp = test_client.get("/document/doc-uuid-1")
        assert "Some content here." in resp.text

    def test_shows_error_for_missing_doc(self, test_client, mock_client):
        mock_client.reconstruct_doc.return_value = None
        resp = test_client.get("/document/does-not-exist")
        assert resp.status_code == 200
        assert "not found" in resp.text.lower()

    def test_handles_client_error(self, test_client, mock_client):
        mock_client.reconstruct_doc.side_effect = RuntimeError("DB error")
        resp = test_client.get("/document/doc-uuid-1")
        assert resp.status_code == 200
        assert "DB error" in resp.text


# ── Ingest page ───────────────────────────────────────────────────────────────


class TestIngestPage:
    def test_get_returns_200(self, test_client):
        resp = test_client.get("/ingest")
        assert resp.status_code == 200

    def test_form_is_present(self, test_client):
        resp = test_client.get("/ingest")
        assert "<form" in resp.text
        assert 'name="content"' in resp.text

    def test_paste_ingest_success(self, test_client, mock_client):
        from cerefox.ingestion.pipeline import IngestResult

        mock_result = IngestResult(
            document_id="new-uuid",
            title="My Note",
            chunk_count=1,
            total_chars=100,
            skipped=False,
        )
        with patch("cerefox.api.routes.IngestionPipeline") as MockPipeline:
            MockPipeline.return_value.ingest_text.return_value = mock_result
            resp = test_client.post(
                "/ingest",
                data={"mode": "paste", "title": "My Note", "content": "# My Note\n\nHello."},
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert "My Note" in resp.text

    def test_paste_ingest_skipped(self, test_client, mock_client):
        from cerefox.ingestion.pipeline import IngestResult

        mock_result = IngestResult(
            document_id="existing-uuid",
            title="My Note",
            chunk_count=1,
            total_chars=100,
            skipped=True,
        )
        with patch("cerefox.api.routes.IngestionPipeline") as MockPipeline:
            MockPipeline.return_value.ingest_text.return_value = mock_result
            resp = test_client.post(
                "/ingest",
                data={"mode": "paste", "title": "My Note", "content": "# My Note\n\nHello."},
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert "Skipped" in resp.text or "skipped" in resp.text.lower()

    def test_paste_ingest_missing_title_shows_error(self, test_client):
        resp = test_client.post(
            "/ingest",
            data={"mode": "paste", "title": "", "content": "Some content."},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "Title" in resp.text or "title" in resp.text.lower()

    def test_paste_ingest_missing_content_shows_error(self, test_client):
        resp = test_client.post(
            "/ingest",
            data={"mode": "paste", "title": "My Note", "content": ""},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "empty" in resp.text.lower() or "Content" in resp.text

    def test_file_upload_ingest_success(self, test_client, mock_client):
        from cerefox.ingestion.pipeline import IngestResult

        mock_result = IngestResult(
            document_id="new-uuid",
            title="uploaded.md",
            chunk_count=2,
            total_chars=200,
            skipped=False,
        )
        with patch("cerefox.api.routes.IngestionPipeline") as MockPipeline:
            MockPipeline.return_value.ingest_text.return_value = mock_result
            resp = test_client.post(
                "/ingest",
                data={"mode": "file", "title": ""},
                files={"file": ("uploaded.md", b"# Hello\n\nContent.", "text/plain")},
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert "Ingested" in resp.text or "uploaded.md" in resp.text

    def test_ingest_pipeline_error_shows_error(self, test_client):
        with patch("cerefox.api.routes.IngestionPipeline") as MockPipeline:
            MockPipeline.return_value.ingest_text.side_effect = RuntimeError("Embed failed")
            resp = test_client.post(
                "/ingest",
                data={"mode": "paste", "title": "My Note", "content": "Content here."},
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 200
        assert "Embed failed" in resp.text


# ── Projects page ─────────────────────────────────────────────────────────────


class TestProjectsPage:
    def test_returns_200(self, test_client):
        resp = test_client.get("/projects")
        assert resp.status_code == 200

    def test_shows_project_names(self, test_client, mock_client):
        mock_client.list_projects.return_value = [
            _make_project(name="Alpha"),
            _make_project(id="proj-2", name="Beta"),
        ]
        resp = test_client.get("/projects")
        assert "Alpha" in resp.text
        assert "Beta" in resp.text

    def test_empty_projects_shows_message(self, test_client, mock_client):
        mock_client.list_projects.return_value = []
        resp = test_client.get("/projects")
        assert resp.status_code == 200
        assert "No projects" in resp.text

    def test_create_project_redirects(self, test_client, mock_client):
        mock_client.create_project.return_value = _make_project(name="New")
        resp = test_client.post(
            "/projects", data={"name": "New", "description": ""}, follow_redirects=False
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"

    def test_create_project_calls_client(self, test_client, mock_client):
        mock_client.create_project.return_value = _make_project(name="New")
        test_client.post("/projects", data={"name": "New", "description": "Desc"})
        mock_client.create_project.assert_called_once_with("New", "Desc")

    def test_delete_project_redirects(self, test_client, mock_client):
        resp = test_client.post(
            "/projects/proj-uuid-1/delete", follow_redirects=False
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/projects"

    def test_delete_project_calls_client(self, test_client, mock_client):
        test_client.post("/projects/proj-uuid-1/delete")
        mock_client.delete_project.assert_called_once_with("proj-uuid-1")

    def test_handles_client_error(self, test_client, mock_client):
        mock_client.list_projects.side_effect = RuntimeError("DB error")
        resp = test_client.get("/projects")
        assert resp.status_code == 200
        assert "DB error" in resp.text
