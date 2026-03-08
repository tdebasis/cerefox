"""All web UI route handlers for Cerefox.

Routes:
    GET  /                          Dashboard — stats + recent docs
    GET  /search                    Knowledge browser (supports ?q=, ?mode=, ?project_id=, ?count=)
    GET  /document/{document_id}    Document viewer
    GET  /ingest                    Ingest form
    POST /ingest                    Handle paste or file upload
    GET  /projects                  Projects list
    POST /projects                  Create project
    POST /projects/{project_id}/delete  Delete project

HTMX detection: routes check the HX-Request header. When present they return
only the relevant HTML partial; otherwise they return the full page.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from cerefox.config import Settings
from cerefox.db.client import CerefoxClient
from cerefox.embeddings.base import Embedder
from cerefox.ingestion.pipeline import IngestionPipeline
from cerefox.retrieval.search import SearchClient

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Dependency helpers ────────────────────────────────────────────────────────


@lru_cache
def _cached_settings() -> Settings:
    return Settings()


@lru_cache
def _cached_client() -> CerefoxClient:
    return CerefoxClient(_cached_settings())


@lru_cache
def _cached_embedder() -> Embedder | None:
    """Return the configured embedder, or None if not available."""
    settings = _cached_settings()
    try:
        if settings.embedder == "ollama":
            from cerefox.embeddings.ollama_embed import OllamaEmbedder

            return OllamaEmbedder(settings.ollama_url, settings.ollama_model)
        else:
            from cerefox.embeddings.mpnet import MpnetEmbedder

            return MpnetEmbedder()
    except Exception as exc:
        logger.warning("Embedder unavailable: %s", exc)
        return None


def get_settings() -> Settings:
    return _cached_settings()


def get_client() -> CerefoxClient:
    return _cached_client()


def get_embedder() -> Embedder | None:
    return _cached_embedder()


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _render(
    templates: Jinja2Templates,
    request: Request,
    template: str,
    ctx: dict[str, Any],
) -> HTMLResponse:
    return templates.TemplateResponse(request, template, ctx)


# ── Dashboard ─────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    client: CerefoxClient = Depends(get_client),
    templates: Jinja2Templates = Depends(get_templates),
):
    ctx: dict[str, Any] = {"active": "dashboard"}
    try:
        recent_docs = client.list_documents(limit=10)
        projects = client.list_projects()
        doc_count = client.count_documents()
        project_count = len(projects)
        ctx.update(
            {
                "recent_docs": recent_docs,
                "projects": projects,
                "doc_count": doc_count,
                "project_count": project_count,
                "error": None,
            }
        )
    except Exception as exc:
        ctx.update(
            {
                "recent_docs": [],
                "projects": [],
                "doc_count": 0,
                "project_count": 0,
                "error": str(exc),
            }
        )
    return _render(templates, request, "dashboard.html", ctx)


# ── Knowledge browser (search) ────────────────────────────────────────────────


@router.get("/search", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = "",
    mode: str = "hybrid",
    project_id: str = "",
    count: int = 10,
    client: CerefoxClient = Depends(get_client),
    embedder: Embedder | None = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
):
    results = None
    error = None
    projects: list[dict] = []

    try:
        projects = client.list_projects()
    except Exception as exc:
        error = str(exc)

    if q and not error:
        pid = project_id or None
        try:
            sc = SearchClient(client, embedder, settings)
            if mode == "fts":
                resp = sc.fts(q, match_count=count, project_id=pid)
            elif mode == "semantic":
                if embedder is None:
                    raise RuntimeError("Embedder not available — install sentence-transformers")
                resp = sc.semantic(q, match_count=count, project_id=pid)
            elif mode == "docs":
                if embedder is None:
                    raise RuntimeError("Embedder not available — install sentence-transformers")
                resp = sc.search_docs(q, match_count=min(count, 5), project_id=pid)
            else:  # hybrid (default)
                if embedder is None:
                    raise RuntimeError("Embedder not available — install sentence-transformers")
                resp = sc.hybrid(q, match_count=count, project_id=pid)
            results = resp
        except Exception as exc:
            error = str(exc)

    ctx = {
        "active": "search",
        "query": q,
        "mode": mode,
        "view": "docs" if mode == "docs" else "chunks",
        "project_id": project_id,
        "count": count,
        "results": results,
        "projects": projects,
        "error": error,
    }

    # HTMX partial: return only the results fragment.
    if _is_htmx(request) and q:
        return _render(templates, request, "partials/search_results.html", ctx)

    return _render(templates, request, "browser.html", ctx)


# ── Document viewer ───────────────────────────────────────────────────────────


@router.get("/document/{document_id}", response_class=HTMLResponse)
def document_view(
    request: Request,
    document_id: str,
    client: CerefoxClient = Depends(get_client),
    templates: Jinja2Templates = Depends(get_templates),
):
    ctx: dict[str, Any] = {"active": "search"}
    try:
        doc_row = client.reconstruct_doc(document_id)
        if doc_row is None:
            ctx["error"] = f"Document {document_id!r} not found."
            ctx["doc"] = None
            ctx["chunks"] = []
        else:
            chunks = client.list_chunks_for_document(document_id)
            ctx.update({"doc": doc_row, "chunks": chunks, "error": None})
    except Exception as exc:
        ctx.update({"doc": None, "chunks": [], "error": str(exc)})
    return _render(templates, request, "document.html", ctx)


# ── Ingest ────────────────────────────────────────────────────────────────────


@router.get("/ingest", response_class=HTMLResponse)
def ingest_form(
    request: Request,
    client: CerefoxClient = Depends(get_client),
    templates: Jinja2Templates = Depends(get_templates),
):
    projects: list[dict] = []
    try:
        projects = client.list_projects()
    except Exception:
        pass
    return _render(templates, request, "ingest.html", {"active": "ingest", "projects": projects})


@router.post("/ingest", response_class=HTMLResponse)
async def ingest_submit(
    request: Request,
    mode: str = Form(...),
    title: str = Form(""),
    project_id: str = Form(""),
    content: str = Form(""),
    file: UploadFile | None = File(None),
    client: CerefoxClient = Depends(get_client),
    embedder: Embedder | None = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
    templates: Jinja2Templates = Depends(get_templates),
):
    result_ctx: dict[str, Any] = {"success": False, "skipped": False, "error": None, "title": ""}
    pid = project_id or None

    try:
        pipeline = IngestionPipeline(client, embedder, settings)

        if mode == "paste":
            if not title.strip():
                result_ctx["error"] = "Title is required for paste mode."
            elif not content.strip():
                result_ctx["error"] = "Content cannot be empty."
            else:
                res = pipeline.ingest_text(content.strip(), title.strip(), project_id=pid)
                result_ctx.update(
                    {"success": not res.skipped, "skipped": res.skipped, "title": res.title}
                )
        elif mode == "file" and file:
            raw = await file.read()
            text = raw.decode("utf-8", errors="replace")
            doc_title = title.strip() or file.filename or "Untitled"
            res = pipeline.ingest_text(
                text, doc_title, source="file", source_path=file.filename, project_id=pid
            )
            result_ctx.update(
                {"success": not res.skipped, "skipped": res.skipped, "title": res.title}
            )
        else:
            result_ctx["error"] = "No content provided."
    except Exception as exc:
        result_ctx["error"] = str(exc)

    if _is_htmx(request):
        return _render(templates, request, "partials/ingest_result.html", result_ctx)

    # Full-page redirect on success, re-render form on error.
    if result_ctx["success"]:
        return RedirectResponse("/ingest?msg=success", status_code=303)
    projects: list[dict] = []
    try:
        projects = client.list_projects()
    except Exception:
        pass
    return _render(
        templates,
        request,
        "ingest.html",
        {"active": "ingest", "projects": projects, "error": result_ctx["error"]},
    )


# ── Projects ──────────────────────────────────────────────────────────────────


@router.get("/projects", response_class=HTMLResponse)
def projects_list(
    request: Request,
    client: CerefoxClient = Depends(get_client),
    templates: Jinja2Templates = Depends(get_templates),
):
    ctx: dict[str, Any] = {"active": "projects"}
    try:
        projects = client.list_projects()
        ctx.update({"projects": projects, "error": None})
    except Exception as exc:
        ctx.update({"projects": [], "error": str(exc)})
    return _render(templates, request, "projects.html", ctx)


@router.post("/projects", response_class=HTMLResponse)
def create_project(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    client: CerefoxClient = Depends(get_client),
):
    try:
        client.create_project(name.strip(), description.strip())
    except Exception as exc:
        logger.error("create_project failed: %s", exc)
    return RedirectResponse("/projects", status_code=303)


@router.post("/projects/{project_id}/delete", response_class=HTMLResponse)
def delete_project(
    request: Request,
    project_id: str,
    client: CerefoxClient = Depends(get_client),
):
    try:
        client.delete_project(project_id)
    except Exception as exc:
        logger.error("delete_project %s failed: %s", project_id, exc)
    return RedirectResponse("/projects", status_code=303)
