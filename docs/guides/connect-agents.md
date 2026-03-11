# Connecting AI Agents to Cerefox

Cerefox exposes its knowledge base through **Supabase MCP** — any agent that supports the Model Context Protocol can search, retrieve, and write notes without any custom server.

---

## Prerequisites

- Supabase project set up (see `setup-supabase.md`)
- Schema and RPCs deployed (`python scripts/db_deploy.py`)
- Some content ingested (`cerefox ingest my-notes.md`)
- Your **project ref**: visible in Supabase → Connect → MCP tab (format: `abcdefghijklmnop`)
- A **Personal Access Token** (PAT): create one at
  `https://supabase.com/dashboard/account/tokens` — name it `cerefox`

> **PAT vs service_role key**: The PAT is a *platform-level* account token used to authenticate
> the MCP server. It is different from the project's anon/service_role API keys, which are for
> direct database access only.

---

## Claude Desktop (chat)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "supabase": {
      "command": "npx",
      "args": [
        "-y",
        "@supabase/mcp-server-supabase@latest",
        "--project-ref", "<your-project-ref>"
      ],
      "env": {
        "SUPABASE_ACCESS_TOKEN": "<your-personal-access-token>"
      }
    }
  }
}
```

**Notes:**
- The `--supabase-url` and `--supabase-key` flags were **removed** from
  `@supabase/mcp-server-supabase@latest`. Do not include them — Claude Desktop will fail to start.
- `SUPABASE_ACCESS_TOKEN` is your PAT (from the account tokens page), not the service_role key.
- Merge the `mcpServers` block into your existing `claude_desktop_config.json` as a top-level key
  alongside any existing keys (e.g. `preferences`). Do not wrap it in an extra `{}`.
- Restart Claude Desktop fully (Cmd+Q, not just close the window) after saving.

---

## Claude Code (CLI)

```bash
# Add the MCP server with PAT authentication
claude mcp add --scope user --transport http supabase \
  "https://mcp.supabase.com/mcp?project_ref=<your-project-ref>" \
  --header "Authorization: Bearer <your-personal-access-token>"

# Verify — should show "connected", not "needs authentication"
claude mcp list
```

Use `--scope user` so the server is available across all your projects.

---

## Verifying the integration

Once connected, test with these prompts:

**Check what tools are available:**
> "What Supabase tools do you have available?"

**Verify the Cerefox schema:**
> "List all tables in my Supabase database that start with 'cerefox'."

Expected: `cerefox_documents`, `cerefox_chunks`, `cerefox_projects`,
`cerefox_document_projects`, `cerefox_metadata_keys`, `cerefox_migrations`

**Run a keyword search:**
> "Call `cerefox_fts_search` with `p_query_text='second brain'` and `p_match_count=3`."

FTS doesn't require an embedding, so it works immediately as a smoke test.

---

## Using Cerefox tools in Claude

### Searching the knowledge base

Ask Claude to use the tools directly:

> "Search my knowledge base for notes about project planning. Use `cerefox_hybrid_search`
> with the query 'project planning'."

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
  p_title: "Meeting notes — 2026-03-10"
  p_content: "# Meeting notes\n\nDiscussed Q1 roadmap..."
  p_source: "agent"
  p_metadata: {"agent_name": "claude", "tags": ["meeting"]}
```

> **Note**: `cerefox_save_note` creates a document record immediately but does **not** embed
> or chunk the content. Run `cerefox ingest` afterwards for the note to become searchable.

---

## Cursor IDE

1. Open **Cursor Settings** → **MCP** → **Add MCP Server**
2. Choose **HTTP** transport, enter the Supabase MCP URL:
   ```
   https://mcp.supabase.com/mcp?project_ref=<your-project-ref>
   ```
3. Add the Authorization header with your PAT.

---

## Custom agents (Python SDK)

Use the Cerefox Python client directly for scripted or embedded agents:

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

All RPCs are defined in `src/cerefox/db/rpcs.sql` and verified deployed to the live database.

### Search RPCs

Every chunk-level search RPC returns:

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
| `doc_project_ids` | UUID[] | Project UUIDs assigned to the document |
| `doc_metadata` | JSONB | Document metadata |

#### `cerefox_fts_search`

Full-text keyword search. Does not require an embedding model.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_text` | TEXT | required | Keyword query |
| `p_match_count` | INT | 10 | Results to return |
| `p_project_id` | UUID | null | Filter by project |

#### `cerefox_semantic_search`

Vector similarity search. Requires a pre-computed query embedding.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_embedding` | VECTOR(768) | required | Query embedding |
| `p_match_count` | INT | 10 | Results to return |
| `p_use_upgrade` | BOOL | false | Use upgrade embedding column |
| `p_project_id` | UUID | null | Filter by project |
| `p_min_score` | FLOAT | 0.0 | Minimum cosine similarity. When called via the Python layer, `CEREFOX_MIN_SEARCH_SCORE` (default 0.65) is applied automatically. |

#### `cerefox_hybrid_search`

Combines FTS and semantic search via linear alpha blending. Two overloads (with/without `p_project_id`).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_text` | TEXT | required | Query string for FTS |
| `p_query_embedding` | VECTOR(768) | required | Query embedding |
| `p_match_count` | INT | 10 | Results to return |
| `p_alpha` | FLOAT | 0.7 | Semantic weight (0=FTS only, 1=semantic only) |
| `p_use_upgrade` | BOOL | false | Use upgrade embedding column |
| `p_project_id` | UUID | null | Filter by project |
| `p_min_score` | FLOAT | 0.0 | Minimum cosine similarity (FTS matches always pass through). When called via the Python layer, `CEREFOX_MIN_SEARCH_SCORE` (default 0.65) is applied automatically. |

#### `cerefox_search_docs`

Document-level search. Runs hybrid search internally, deduplicates by document (keeping the
best-scoring chunk per document), then returns up to `p_match_count` **distinct documents**
with their full reconstructed content. Two overloads (with/without `p_project_id`).

Use this when you want complete notes rather than isolated chunks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_query_text` | TEXT | required | Query string for FTS |
| `p_query_embedding` | VECTOR(768) | required | Query embedding |
| `p_match_count` | INT | 5 | Max documents to return |
| `p_alpha` | FLOAT | 0.7 | Semantic weight |
| `p_project_id` | UUID | null | Filter by project |
| `p_min_score` | FLOAT | 0.0 | Minimum cosine similarity |

Returns: `document_id`, `doc_title`, `doc_source`, `doc_metadata`, `best_score`,
`best_chunk_heading_path`, `full_content`, `chunk_count`, `total_chars`

---

### Document RPCs

#### `cerefox_reconstruct_doc`

Fetch a full document by ID, concatenating all chunks in order.

| Parameter | Type | Description |
|-----------|------|-------------|
| `p_document_id` | UUID | Document to reconstruct |

Returns: `document_id`, `doc_title`, `doc_source`, `doc_metadata`, `full_content`,
`chunk_count`, `total_chars`

#### `cerefox_context_expand`

Small-to-big retrieval: given a set of chunk IDs, returns those chunks **plus their immediate
neighbours** (±`p_window_size` chunks within the same document). Use after chunk-level search
to recover surrounding context without fetching the full document.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_chunk_ids` | UUID[] | required | Array of chunk UUIDs from search results |
| `p_window_size` | INT | 1 | Chunks to expand in each direction |

Returns: `chunk_id`, `document_id`, `chunk_index`, `title`, `content`, `heading_path`,
`heading_level`, `doc_title`, `is_seed` (TRUE for the original seed chunks)

#### `cerefox_save_note`

Create a document record directly from an agent without going through the ingestion pipeline.
The note is stored but **not embedded** — run `cerefox ingest` to make it searchable.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `p_title` | TEXT | required | Note title |
| `p_content` | TEXT | required | Markdown content |
| `p_source` | TEXT | `'agent'` | Origin label |
| `p_project_id` | UUID | null | Project to assign |
| `p_metadata` | JSONB | `{}` | Metadata (agent name, tags, etc.) |

Returns: `id`, `title`, `created_at`

---

### Metadata RPCs

#### `cerefox_upsert_metadata_key`

Register or update a metadata key in the key registry.

| Parameter | Type | Description |
|-----------|------|-------------|
| `p_key` | TEXT | Key name (snake_case) |
| `p_label` | TEXT | Human-readable label (optional) |
| `p_description` | TEXT | Description (optional) |

#### `cerefox_delete_metadata_key`

Remove a key from the registry.

| Parameter | Type | Description |
|-----------|------|-------------|
| `p_key` | TEXT | Key to remove |

#### `cerefox_list_metadata_keys`

List all registered metadata keys. No parameters. Returns: `key`, `label`, `description`,
`created_at`, `updated_at`.

---

## Response size

Cerefox's default `max_response_bytes = 65000` matches the Supabase MCP limit. If you're
using a different MCP client with a lower limit, reduce it via `CEREFOX_MAX_RESPONSE_BYTES`
in your `.env`.
