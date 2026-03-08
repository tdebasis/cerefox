# Cerefox Implementation Plan

> **Approach**: Iterative and agile. Each phase delivers working functionality.
> Update this file as phases are completed and new work is planned.

---

## Phase 1: Foundation — Project Setup & Database ✓

**Goal**: Runnable Python project with database schema deployed to Supabase.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1.1 | Initialize Python project (pyproject.toml, uv, ruff config) | Done | uv project, ruff at line-length 100 |
| 1.2 | Create project directory structure (src/cerefox/*) | Done | Matches CLAUDE.md tree |
| 1.3 | Write config module (pydantic-settings, .env support) | Done | `src/cerefox/config.py`, CEREFOX_ prefix |
| 1.4 | Write database schema SQL (documents, chunks, projects tables) | Done | `src/cerefox/db/schema.sql` — HNSW, FTS GENERATED col |
| 1.5 | Write search RPC SQL (hybrid, FTS, semantic, reconstruct) | Done | `src/cerefox/db/rpcs.sql` — all SECURITY DEFINER |
| 1.6 | Create DB client wrapper (Supabase Python client) | Done | `src/cerefox/db/client.py` — lazy init, typed methods |
| 1.7 | Write `scripts/db_deploy.py` — apply full schema to a fresh instance | Done | psycopg2, `--dry-run`, `--reset` flags |
| 1.8 | Write `scripts/db_status.py` — verify schema and report table stats | Done | Checks extensions, tables, functions, indexes, row counts |
| 1.9 | Deploy schema to Supabase using db_deploy.py | Pending | Requires real credentials — user action needed |
| 1.10 | Write tests for config module and DB client (unit, mocked) | Done | 40 tests pass — `tests/test_config.py`, `tests/test_db_client.py` |
| 1.11 | Write `docs/guides/setup-supabase.md` and `docs/guides/configuration.md` | Done | Step-by-step setup guide + full config reference |

**Deliverable**: Schema running on Supabase, Python project builds and imports, deploy script and Supabase setup guide complete.

---

## Phase 2: Chunking & Embeddings ✓

**Goal**: Markdown chunking engine and pluggable embedding system.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 2.1 | Implement heading-based markdown chunker | Done | `src/cerefox/chunking/markdown.py` — H1>H2>H3 cascade, regex split |
| 2.2 | Add chunk size management (max/min chars, paragraph fallback) | Done | Heading boundaries never merged; paragraph pieces may merge if tiny |
| 2.3 | Implement Embedder protocol (base.py) | Done | `@runtime_checkable` Protocol |
| 2.4 | Implement all-mpnet-base-v2 embedder | Done | `src/cerefox/embeddings/mpnet.py` — lazy model load |
| 2.5 | Implement Ollama embedder | Done | `src/cerefox/embeddings/ollama_embed.py` — httpx, lazy import |
| 2.6 | Write tests for chunking: empty doc, headings only, oversized sections, no headings | Done | 31 tests in `tests/chunking/test_markdown.py` |
| 2.7 | Write tests for embedders: mock model output, verify dimension, batch handling | Done | 21 tests in `tests/embeddings/test_embedders.py` |

**Deliverable**: Can parse any markdown file into heading-aware chunks with embeddings. Tests pass.

---

## Phase 3: Ingestion Pipeline & CLI ✓

**Goal**: End-to-end ingestion from markdown file to database, via CLI.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 3.1 | Implement ingestion pipeline (parse → chunk → embed → store) | Done | `src/cerefox/ingestion/pipeline.py` |
| 3.2 | Add content hash deduplication | Done | SHA-256; returns skipped=True if hash already exists |
| 3.3 | Build CLI with Click (ingest command) | Done | `src/cerefox/cli.py` — file + --paste (stdin) modes |
| 3.4 | Add CLI commands: list-docs, delete-doc, list-projects | Done | All tested with Click CliRunner |
| 3.5 | Add file system backup | Done | `src/cerefox/backup/fs_backup.py` — atomic JSON writes |
| 3.6 | Write `scripts/backup_create.py` and `scripts/backup_restore.py` | Done | Idempotent restore; --dry-run flag on both |
| 3.7 | Write tests for pipeline: dedup logic, chunk-to-DB mapping (mocked DB) | Done | `tests/ingestion/test_pipeline.py`, `test_backup.py`, `test_cli.py` |
| 3.8 | Integration test: ingest a real MD file into Supabase | Pending | `@pytest.mark.integration` — requires live Supabase |

**Deliverable**: `cerefox ingest my-notes.md --project "creative projects"` works end-to-end. Backup scripts documented.

---

## Phase 4: Search & Retrieval ✓

**Goal**: Working search RPCs and retrieval logic.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 4.1 | Deploy search RPCs to Supabase | Pending | Requires real credentials — user action needed |
| 4.2 | Implement Python search client (wraps RPC calls) | Done | `src/cerefox/retrieval/search.py` — SearchClient, SearchResult, SearchResponse |
| 4.3 | Add CLI search command | Done | `cerefox search` — hybrid/fts/semantic modes, --alpha, --count, --project |
| 4.4 | Implement response size management (truncation, metadata) | Done | `_build_response()` + `_estimate_bytes()`; configurable via `CEREFOX_MAX_RESPONSE_BYTES` |
| 4.5 | Write tests for search client: response assembly, size truncation, metadata | Done | 22 tests in `tests/retrieval/test_search.py` (164 total passing) |
| 4.6 | Integration test: search with real ingested content | Pending | `@pytest.mark.integration` — requires live Supabase |
| 4.7 | Connect via Supabase MCP and verify agent access | Pending | Requires live Supabase — user action needed |
| 4.8 | Implement `cerefox_save_note` RPC (agent write tool) | Done | `src/cerefox/db/rpcs.sql` + `client.save_note()` — quick note capture, no chunking |
| 4.9 | Write `docs/guides/connect-agents.md` (Claude, Cursor, generic MCP client) | Done | Claude Desktop, Cursor IDE, Python SDK, full RPC reference |

**Deliverable**: Agents can search and write to Cerefox via MCP. CLI search works. Unit tests pass. Agent connection guide complete.

---

## Phase 5: Web Application (Basic) ✓

**Goal**: Local web UI for browsing knowledge and ingesting content.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 5.1 | FastAPI app skeleton with Jinja2 + HTMX | Done | `src/cerefox/api/app.py` + `routes.py` — create_app() factory, dependency injection |
| 5.2 | Dashboard page (doc count, recent docs, projects) | Done | `web/templates/dashboard.html` — stats cards, recent docs table, projects |
| 5.3 | Knowledge browser page (search, filter by project/tags) | Done | `web/templates/browser.html` — HTMX search, mode selector, project filter |
| 5.4 | Document viewer page (reconstructed doc with chunk boundaries) | Done | `web/templates/document.html` — chunk list with heading breadcrumbs |
| 5.5 | Ingest page (upload MD files, paste content) | Done | `web/templates/ingest.html` — paste + file upload, HTMX feedback |
| 5.6 | Project management page (CRUD projects) | Done | `web/templates/projects.html` — list, create, delete |
| 5.7 | Write `docs/guides/setup-local.md` (local Docker setup guide) | Done | Step-by-step local Docker + Postgres setup |
| 5.8 | Write `docs/guides/ops-scripts.md` (backup, restore, migrate) | Done | All operational scripts documented |

**Deliverable**: Usable web UI for managing the knowledge base locally. Local setup guide complete.

---

## Phase 6: Enhanced Features ✓

**Goal**: Production-quality features for daily use.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 6.1 | PDF → Markdown converter | Done | `src/cerefox/chunking/converters.py` — pypdf (optional dep), page sections |
| 6.2 | DOCX → Markdown converter | Done | Same file — python-docx (optional dep), heading style mapping |
| 6.3 | Small-to-big context expansion RPC | Done | `cerefox_context_expand` SQL RPC + `client.context_expand()` |
| 6.4 | Async ingestion with status tracking | Deferred | Requires queue infrastructure; not justified for single-user V1 |
| 6.5 | Ingestion error UI (status panel, retry) | Deferred | Depends on 6.4 |
| 6.6 | Metadata schema management (define custom fields) | Deferred | Complexity not justified for V1; JSONB metadata is sufficient |
| 6.7 | Batch ingestion (directory of files) | Done | `cerefox ingest-dir DIR/ --pattern "*.md" --recursive --dry-run` |
| 6.8 | Git backup integration | Done | `FileSystemBackup.create(git_commit=True)` + `--git-commit` flag |

**Deliverable**: Robust ingestion pipeline with multiple input formats.

---

## Phase 7: Deployment & Open Source ✓

**Goal**: Packageable, deployable, and shareable.

| # | Task | Status | Notes |
|---|------|--------|-------|
| 7.1 | Dockerfile for the web app | Done | Multi-stage build (builder + runtime), uvicorn entrypoint, healthcheck |
| 7.2 | docker-compose.yml for full local stack | Done | Postgres+pgvector + cerefox web UI + named volumes |
| 7.3 | Cloud Run deployment config | Done | `docs/guides/setup-cloud-run.md` — build, push, deploy, cost estimate |
| 7.4 | README.md — project overview, quickstart, links to guides | Done | Feature table, architecture, MCP config, CLI reference, docs index |
| 7.5 | `docs/guides/quickstart.md` — zero to first document in < 15 min | Done | 8-step guide from clone to first search + agent connection |
| 7.6 | `docs/guides/setup-cloud-run.md` — GCP Cloud Run deployment | Done | Full deploy guide with cost estimate and access control options |
| 7.7 | `docs/guides/contributing.md` — adding embedders, converters, commands | Done | Extension points for all major components |
| 7.8 | License file, .env.example | Done | MIT license (pre-existing) + .env.example with all settings |
| 7.9 | First release (v0.1.0) | Ready | 218 tests passing, all phases complete — tag when credentials available |

**Deliverable**: Open source release. All setup guides complete. Any new user can go from zero to running Cerefox in one sitting.

---

## Progress Log

Record completed milestones here as we go.

| Date | Milestone | Notes |
|------|-----------|-------|
| 2026-03-07 | Project kickoff | Created CLAUDE.md, solution design, plan, TODO, requirements |
| 2026-03-07 | Phase 1 complete | Python project, full schema SQL, search RPCs, DB client, deploy/status scripts, 40 unit tests passing, Supabase setup guide and config reference written |
| 2026-03-07 | Phase 2 complete | Heading-aware markdown chunker, Embedder protocol, mpnet + Ollama embedders, 52 new tests (92 total passing) |
| 2026-03-08 | Phase 3 complete | Ingestion pipeline, SHA-256 dedup, Click CLI (ingest/list-docs/delete-doc/list-projects), JSON backup/restore, 50 new tests (142 total passing) |
| 2026-03-08 | Phase 4 complete | SearchClient (hybrid/fts/semantic/reconstruct), response size management, CLI search command, cerefox_save_note RPC, agent connection guide, 22 new tests (164 total passing) |
| 2026-03-08 | Phase 5 complete | FastAPI web UI (dashboard/search/ingest/projects/doc-viewer), Jinja2+HTMX+Pico.css, `cerefox web` CLI command, local setup guide, ops-scripts guide, 34 new tests (198 total passing) |
| 2026-03-08 | Phase 6 complete | PDF+DOCX converters, cerefox_context_expand RPC, cerefox ingest-dir, git backup, 20 new tests (218 total passing) |
| 2026-03-08 | Phase 7 complete | Dockerfile, docker-compose.yml, Cloud Run guide, README, quickstart, contributing guide, .env.example — v0.1.0 ready |
| 2026-03-08 | Post-release: document search | cerefox_search_docs RPC deployed; DocResult/DocSearchResponse; web UI Documents mode; test-data corpus; 236 tests passing |

---

## Post-Release Improvements

Work completed after the v0.1.0 baseline.

| # | Task | Status | Notes |
|---|------|--------|-------|
| P.1 | Supabase end-to-end testing — real connection, ingest, search | Done | Session pooler URL (IPv4), service_role key; Intel Mac + Python 3.13 → Ollama |
| P.2 | Intel Mac / Python 3.13 platform fix in pyproject.toml | Done | `torch<2.3.0` constraint for x86_64/darwin; Ollama path documented in README |
| P.3 | `cerefox_search_docs` SQL RPC — document-level hybrid search | Done | `src/cerefox/db/rpcs.sql` — deduplicates by document, reconstructs full content via STRING_AGG |
| P.4 | `DocResult` + `DocSearchResponse` dataclasses + `search_docs()` | Done | `src/cerefox/retrieval/search.py` + `src/cerefox/db/client.py` — parallel to chunk search layer |
| P.5 | Tests for document search (18 new tests) | Done | `tests/retrieval/test_search.py` + `tests/test_db_client.py` — 236 total passing |
| P.6 | Fix test_config.py for `.env` file presence | Done | `Settings(_env_file=None)` in tests that use `clear=True`; pydantic-settings reads `.env` even when env is cleared |
| P.7 | `test-data/` corpus — 6 diverse markdown documents | Done | cerefox-overview, knowledge-management, espresso, ancient-rome, python-concurrency, worldbuilding |
| P.8 | Web UI: "Documents (full)" search mode | Done | `browser.html` 4th mode option; `routes.py` calls `search_docs()`; `search_results.html` branches on `view` |

## Current Focus

**236 tests passing.** Document-level search implemented and deployed to Supabase. Web UI updated with Documents search mode.
