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

---

## Test Layers

### 1. Supabase REST API — Document & Project Lifecycle

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

| Class | Test | Use Case | Status |
|-------|------|----------|--------|
| `TestDocumentLifecycle` | `test_ingest_and_verify` | Ingest → verify doc + chunks exist → FTS search finds it → update metadata → reconstruct → delete | Done |
| `TestContentHashDedup` | `test_duplicate_content_is_skipped` | Re-ingest same content; second call returns `skipped=True` | Done |
| `TestProjectCRUD` | `test_project_lifecycle` | Create → list → get → update → delete a project | Done |
| `TestDocumentProjectAssignment` | `test_assign_and_count` | Assign doc to project, verify doc count in project, unassign | Done |

### 2. Supabase REST API — Document Versioning

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

| Class | Test | Use Case | Status |
|-------|------|----------|--------|
| `TestVersioningLifecycle` | `test_update_creates_version_and_archived_chunks` | Update doc content → verify version row created, old chunks archived (`version_id` set), new current chunks inserted | Done |
| `TestVersioningLifecycle` | `test_metadata_only_update_skips_versioning` | Update only metadata (title/tags, same content) → verify no version row is created | Done |

### 3. Edge Functions (HTTP POST → Supabase Edge Functions)

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

Requires `CEREFOX_SUPABASE_ANON_KEY` in `.env`. Skipped if not available.

| Class | Test | Use Case | Status |
|-------|------|----------|--------|
| `TestEdgeFunctionIngest` | `test_ingest_and_dedup` | POST new doc → verify response + DB row; re-POST with `update_if_exists=true` → verify updated; re-POST same content → verify dedup/skipped | Done |
| `TestEdgeFunctionSearch` | `test_fts_search` | Search for ingested doc via `cerefox-search` Edge Function (FTS mode) | Done |
| `TestEdgeFunctionMetadata` | `test_list_metadata_keys` | Call `cerefox-metadata` Edge Function, verify test doc's metadata keys appear | Done |

### 4. Small-to-Big Retrieval

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

| Class | Test | Use Case | Status |
|-------|------|----------|--------|
| `TestSmallToBigRetrieval` | `test_small_doc_is_not_partial` | Ingest a short doc; `search_docs` returns `is_partial=False` and `full_content` matches reconstructed doc | Done |
| `TestSmallToBigRetrieval` | `test_large_doc_is_partial` | Ingest a large doc (>20 000 chars); `search_docs` returns `is_partial=True` and `chunk_count` (returned) < total chunk count | Done |
| `TestSmallToBigRetrieval` | `test_context_window_zero_returns_fewer_chunks_than_window_one` | Same large doc with `p_context_window=0` vs `p_context_window=1` — window=0 returns matched chunks only; window=1 returns matched + neighbours | Done |
| `TestSmallToBigRetrieval` | `test_partial_result_has_no_duplicate_content` | Large doc with `p_context_window=2`; verify no chunk content appears twice in the assembled result | Done |

### 5. Metadata-Filtered Search

File: `tests/e2e/test_api_e2e.py` — marker: `@pytest.mark.e2e`

Two docs are ingested with different metadata; each test asserts only the matching doc is returned.

| Class | Test | Use Case | Status |
|-------|------|----------|--------|
| `TestMetadataFilteredSearch` | `test_metadata_filter_python_search_docs` | `SearchClient.search_docs()` with `metadata_filter` — only doc A (matching filter) returned | Done |
| `TestMetadataFilteredSearch` | `test_metadata_filter_hybrid_search` | `SearchClient.hybrid()` with `metadata_filter` — only doc B (matching filter) returned | Done |
| `TestMetadataFilteredSearch` | `test_metadata_filter_fts_search` | `SearchClient.fts()` with `metadata_filter` — only matching doc returned | Done |
| `TestMetadataFilteredSearch` | `test_metadata_filter_edge_function` | `cerefox-search` Edge Function with `metadata_filter` JSON body field | Done |
| `TestMetadataFilteredSearch` | `test_metadata_filter_no_match_returns_empty` | Filter that matches no documents returns empty results | Done |

### 6. Web UI (Playwright browser tests)

File: `tests/e2e/test_ui_e2e.py` — marker: `@pytest.mark.ui`

Requires: web app running at `http://127.0.0.1:8000/`

| Class | Test | Use Case | Status |
|-------|------|----------|--------|
| `TestDashboard` | `test_loads_and_shows_stats` | Dashboard renders with doc count, recent docs, and projects | Done |
| `TestIngestPaste` | `test_paste_ingest_creates_document` | Paste content → submit → verify doc appears in search → cleanup | Done |
| `TestSearch` | `test_search_page_loads` | Knowledge Browser page renders with search form | Done |
| `TestSearch` | `test_fts_search_returns_results` | FTS search returns results with no error | Done |
| `TestProjects` | `test_project_crud` | Create project via UI → verify in list → delete → verify gone | Done |
| `TestDocumentView` | `test_document_page_loads` | Navigate from dashboard to a document detail page | Done |
| `TestVersioningUI` | `test_upload_new_file_creates_version_row` | Upload a `.md` file → update with new file → verify version download link appears in UI | Done |

### 7. MCP Server (future)

| # | Use Case | Status |
|---|----------|--------|
| 7.1 | MCP `cerefox_search` tool — end-to-end via stdio transport | TODO |
| 7.2 | MCP `cerefox_ingest` tool — end-to-end via stdio transport | TODO |
| 7.3 | MCP `cerefox_list_metadata_keys` tool — end-to-end via stdio transport | TODO |
| 7.4 | MCP `cerefox_get_document` tool — end-to-end via stdio transport | TODO |
| 7.5 | MCP `cerefox_list_versions` tool — end-to-end via stdio transport | TODO |

---

## TODO / Future Cases

- Hybrid and semantic search e2e (requires embedding cost per run; currently only FTS is tested via Edge Functions)
- Project-filtered search (search with `project_id` constraint)
- Large document chunking verification (chunk sizes, heading paths)
- Edge Function error handling (missing required fields, invalid JSON, unknown project)
- Edit document metadata via UI (add/remove/rename metadata keys)
- Document download (`.md` export) via UI
- Metadata filter via web UI (filter row inputs)
- Version retrieval via CLI (`cerefox get-doc --version`)
