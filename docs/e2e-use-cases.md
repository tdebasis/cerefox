# E2E Test Use Cases

End-to-end tests that exercise the real Supabase backend and/or the web UI.
These are **opt-in** — they are excluded from the default `uv run pytest` run.

## How to Run

```bash
# API e2e tests (Supabase REST + Edge Functions)
uv run pytest -m e2e

# UI e2e tests (Playwright, requires web app running at http://127.0.0.1:8000)
uv run pytest -m ui

# Both
uv run pytest -m "e2e or ui"
```

All test data uses an `[E2E]` or `[E2E-UI]` prefix in titles and is cleaned up
after each run, even on failure.

## Configuration

- **Supabase REST API tests**: Use credentials from `.env` (`CEREFOX_SUPABASE_URL`, `CEREFOX_SUPABASE_KEY`)
- **Edge Function tests**: Need a JWT-format key. Set `CEREFOX_SUPABASE_ANON_KEY` in `.env` (the Supabase anon key from Dashboard > Settings > API). Skipped if not available.
- **UI tests**: Require the web app to be running (`uv run uvicorn cerefox.api.app:app`)

## Test Layers

### 1. Supabase REST API (Python client → PostgREST)

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

| # | Use Case | Status |
|---|----------|--------|
| 1.1 | **Ingest a document** — insert doc + chunks, verify doc and chunk rows exist | Done |
| 1.2 | **List documents** — verify the ingested doc appears in list_documents | Done |
| 1.3 | **Get document by ID** — fetch and verify fields | Done |
| 1.4 | **Find document by title** — exact title lookup | Done |
| 1.5 | **Update document metadata** — change metadata, verify persisted | Done |
| 1.6 | **List chunks for document** — verify chunk count and content | Done |
| 1.7 | **Reconstruct document** — call reconstruct_doc RPC, verify full_content | Done |
| 1.8 | **List metadata keys** — verify the RPC returns keys from test doc metadata | Done |
| 1.9 | **FTS search** — keyword search finds the test document | Done |
| 1.10 | **Delete document** — delete and verify it's gone | Done |
| 1.11 | **Project CRUD** — create, list, get, update, delete a project | Done |
| 1.12 | **Document-project assignment** — assign doc to project, verify, unassign | Done |
| 1.13 | **Count documents** — verify count with and without project filter | Done |
| 1.14 | **Content hash deduplication** — ingest same content twice, second is skipped | Done |

### 2. Edge Functions (HTTP POST → Supabase Edge Functions)

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

Requires `CEREFOX_SUPABASE_ANON_KEY` in `.env` (JWT format). Skipped otherwise.

| # | Use Case | Status |
|---|----------|--------|
| 2.1 | **cerefox-ingest** — POST a document, verify response, verify doc in DB | Done |
| 2.2 | **cerefox-search** — search for the ingested doc via FTS mode | Done |
| 2.3 | **cerefox-metadata** — list metadata keys, verify test doc's keys appear | Done |
| 2.4 | **cerefox-ingest update** — re-ingest with update_if_exists=true, verify updated | Done |
| 2.5 | **cerefox-ingest dedup** — re-ingest same content, verify skipped | Done |

### 3. Web UI (Playwright browser tests)

File: `tests/e2e/test_ui_e2e.py` — marker: `@pytest.mark.ui`

Requires: web app running at `http://127.0.0.1:8000/`

| # | Use Case | Status |
|---|----------|--------|
| 3.1 | **Dashboard loads** — verify stats and recent docs render | Done |
| 3.2 | **Paste ingest** — full flow: paste content → verify in search → delete | Done |
| 3.3 | **Search page loads** — verify knowledge browser renders | Done |
| 3.4 | **FTS search** — search and verify no errors | Done |
| 3.5 | **Project CRUD** — create → verify → delete via UI | Done |
| 3.6 | **Document detail** — navigate from dashboard → document detail page | Done |

### 4. MCP Server (future)

| # | Use Case | Status |
|---|----------|--------|
| 4.1 | MCP cerefox_search tool — end-to-end via stdio transport | TODO |
| 4.2 | MCP cerefox_ingest tool — end-to-end via stdio transport | TODO |
| 4.3 | MCP cerefox_list_metadata_keys tool — end-to-end via stdio transport | TODO |

## TODO / Future Cases

- Semantic search and hybrid search e2e (requires embedding cost per run)
- Context expand RPC
- Document update-content (re-chunk + re-embed via web UI)
- Project-filtered search
- Large document chunking verification (chunk sizes, heading paths)
- Edge Function error handling (missing fields, invalid JSON)
- Edit document metadata via UI (add/remove/rename metadata keys)
- File upload ingest via UI
- Document download (.md export)
