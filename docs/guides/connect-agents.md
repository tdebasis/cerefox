# Connecting AI Agents to Cerefox

Cerefox exposes its knowledge base through **Supabase MCP** — any agent that supports the Model Context Protocol can search, retrieve, and write notes without any custom server.

---

## Prerequisites

- Supabase project set up (see `setup-supabase.md`)
- Schema and RPCs deployed (`python scripts/db_deploy.py`)
- Some content ingested (`cerefox ingest my-notes.md`)

---

## Supabase MCP (Recommended)

Supabase provides a first-class MCP server that exposes all your database functions (including Cerefox's RPCs) as tools. This is the zero-infrastructure path.

### Step 1 — Get your Supabase credentials

You need:
- **Project ref**: found in your Supabase project URL (`https://app.supabase.com/project/<ref>`)
- **Service role key**: Project Settings → API → `service_role` key

### Step 2 — Configure Claude Desktop (or any MCP client)

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "supabase": {
      "command": "npx",
      "args": [
        "-y",
        "@supabase/mcp-server-supabase@latest",
        "--supabase-url", "https://<your-project-ref>.supabase.co",
        "--supabase-key", "<your-service-role-key>"
      ]
    }
  }
}
```

Restart Claude Desktop. The Supabase MCP server will now expose all Cerefox RPCs as callable tools.

### Step 3 — Verify the tools are available

In Claude, ask: *"What Supabase tools do you have available?"*

You should see:
- `cerefox_hybrid_search` — recommended default for chunk-level results
- `cerefox_fts_search` — keyword-only search
- `cerefox_semantic_search` — vector-only search
- `cerefox_search_docs` — document-level search (returns full notes, not chunks)
- `cerefox_reconstruct_doc` — fetch full document by ID
- `cerefox_context_expand` — expand chunk results with neighbouring chunks
- `cerefox_save_note` — quick note capture from agents

---

## Using Cerefox tools in Claude

### Searching the knowledge base

Ask Claude to use the tools directly:

> "Search my knowledge base for notes about project planning. Use `cerefox_hybrid_search` with the query 'project planning'."

Or set up a system prompt so Claude searches automatically:

```
You have access to a personal knowledge base via Cerefox Supabase tools.
When answering questions, first search for relevant context using
cerefox_hybrid_search with p_match_count=10 and p_alpha=0.7.
Always cite the doc_title and chunk content in your response.
```

### Saving a note

Claude (or any agent) can capture information directly:

```
Tool: cerefox_save_note
Parameters:
  p_title: "Meeting notes — 2026-03-08"
  p_content: "# Meeting notes\n\nDiscussed Q1 roadmap..."
  p_source: "agent"
  p_metadata: {"agent_name": "claude", "tags": ["meeting"]}
```

> **Note**: `cerefox_save_note` creates a document record immediately but does **not** embed or chunk the content. Run `cerefox ingest` afterwards for the note to become searchable.

---

## Cursor IDE

Cursor supports MCP via `cursor-mcp` or direct Supabase MCP integration.

1. Install the Supabase MCP extension or configure it in Cursor settings.
2. Provide the same Supabase URL + service role key.
3. Cursor will expose the Cerefox RPCs as context tools in your AI chat.

---

## Custom agents (Python SDK)

Use the Cerefox Python client directly:

```python
from cerefox.config import Settings
from cerefox.db.client import CerefoxClient
from cerefox.embeddings.mpnet import MpnetEmbedder
from cerefox.retrieval.search import SearchClient

settings = Settings()            # reads from .env
client = CerefoxClient(settings)
embedder = MpnetEmbedder()
sc = SearchClient(client, embedder, settings)

resp = sc.hybrid("what did I write about Rust?", match_count=5)
for hit in resp.results:
    print(f"[{hit.score:.2f}] {hit.doc_title} — {hit.content[:200]}")
```

---

## RPC Reference

All RPCs are in `src/cerefox/db/rpcs.sql`.  Every search RPC returns:

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | UUID | ID of the matching chunk |
| `document_id` | UUID | ID of the parent document |
| `chunk_index` | INT | Position within the document |
| `title` | TEXT | Chunk heading (H1/H2/H3) |
| `content` | TEXT | Full chunk text |
| `heading_path` | TEXT[] | Breadcrumb: e.g. `["Doc Title", "Section", "Sub"]` |
| `heading_level` | INT | 0–3 |
| `score` | FLOAT | Relevance score (higher = more relevant) |
| `doc_title` | TEXT | Parent document title |
| `doc_source` | TEXT | Origin: `"file"`, `"paste"`, `"agent"` |
| `doc_project_id` | UUID | Project UUID (nullable) |
| `doc_metadata` | JSONB | Document metadata |

### `cerefox_hybrid_search`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_text` | TEXT | required | Query string for FTS |
| `p_query_embedding` | VECTOR(768) | required | Query embedding |
| `p_match_count` | INT | 10 | Results to return |
| `p_alpha` | FLOAT | 0.7 | Semantic weight (0=FTS, 1=semantic) |
| `p_use_upgrade` | BOOL | false | Use upgrade embedding column |
| `p_project_id` | UUID | null | Filter by project |
| `p_min_score` | FLOAT | 0.0 | Minimum cosine similarity. Chunks that matched the FTS `@@` operator always pass through regardless of their vector score. Only vector-only results are filtered. When called via the Python layer, `CEREFOX_MIN_SEARCH_SCORE` (default 0.65) is applied automatically. |

### `cerefox_fts_search`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_text` | TEXT | required | Keyword query |
| `p_match_count` | INT | 10 | Results to return |
| `p_project_id` | UUID | null | Filter by project |

### `cerefox_semantic_search`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_embedding` | VECTOR(768) | required | Query embedding |
| `p_match_count` | INT | 10 | Results to return |
| `p_use_upgrade` | BOOL | false | Use upgrade embedding |
| `p_project_id` | UUID | null | Filter by project |

### `cerefox_reconstruct_doc`

| Parameter | Type | Description |
|-----------|------|-------------|
| `p_document_id` | UUID | Document to reconstruct |

Returns: `document_id`, `doc_title`, `doc_source`, `doc_metadata`, `full_content`, `chunk_count`, `total_chars`

### `cerefox_save_note`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_title` | TEXT | required | Note title |
| `p_content` | TEXT | required | Markdown content |
| `p_source` | TEXT | `'agent'` | Origin label |
| `p_project_id` | UUID | null | Project to assign |
| `p_metadata` | JSONB | `{}` | Metadata (agent name, tags, etc.) |

Returns: `id`, `title`, `created_at`

### `cerefox_search_docs`

Document-level search. Runs hybrid search internally, deduplicates by document (keeping the best-scoring chunk per document), then returns up to `p_match_count` **distinct documents** with their full reconstructed content.

Use this when you want complete notes rather than isolated chunks — ideal for personal knowledge bases where full context is more valuable than pinpoint precision.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_text` | TEXT | required | Query string for FTS |
| `p_query_embedding` | VECTOR(768) | required | Query embedding |
| `p_match_count` | INT | 5 | Max documents to return |
| `p_alpha` | FLOAT | 0.7 | Semantic weight (0=FTS, 1=semantic) |
| `p_project_id` | UUID | null | Filter by project |
| `p_min_score` | FLOAT | 0.0 | Minimum cosine similarity (see `cerefox_hybrid_search` note above) |

Returns: `document_id`, `doc_title`, `doc_source`, `doc_metadata`, `best_score`, `best_chunk_heading_path`, `full_content`, `chunk_count`, `total_chars`

### `cerefox_context_expand`

Small-to-big retrieval: given a set of chunk IDs from a search result, returns those chunks **plus their immediate neighbours** (±`p_window_size` chunks within the same document). Use this after chunk-level search to recover more surrounding context without fetching the full document.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_chunk_ids` | UUID[] | required | Array of chunk UUIDs from search results |
| `p_window_size` | INT | 1 | Chunks to expand in each direction |

Returns: `chunk_id`, `document_id`, `chunk_index`, `title`, `content`, `heading_path`, `heading_level`, `doc_title`, `is_seed` (TRUE for the original seed chunks)

---

## Response size

Cerefox's default `max_response_bytes = 65000` matches the Supabase MCP limit. If you're using a different MCP client with a lower limit, reduce it via `CEREFOX_MAX_RESPONSE_BYTES` in your `.env`.
