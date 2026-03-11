# Cerefox Configuration Reference

All settings use the `CEREFOX_` environment variable prefix and can be set in a `.env` file in the project root, or as actual environment variables.

Copy `.env.example` to `.env` to get started:
```bash
cp .env.example .env
```

---

## Supabase / Database

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `CEREFOX_SUPABASE_URL` | `""` | For app | Supabase project URL. Found in: Project Settings → API → Project URL |
| `CEREFOX_SUPABASE_KEY` | `""` | For app | Service role key. Found in: Project Settings → API → service_role key. **Keep secret.** |
| `CEREFOX_DATABASE_URL` | `""` | For scripts | Direct Postgres connection URL. Found in: Project Settings → Database → Connection string (URI). Required for `db_deploy.py` and `db_status.py`. |

**When each is needed:**
- `CEREFOX_SUPABASE_URL` + `CEREFOX_SUPABASE_KEY` — used by the Python app (ingestion, search, CLI, web UI) via supabase-py
- `CEREFOX_DATABASE_URL` — used only by the deployment scripts (psycopg2 direct connection)

---

## Embeddings

Cerefox uses cloud-based embedding APIs. Local models (mpnet, Ollama) are not supported — they require large downloads, fail on some hardware, and add installation complexity.

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_EMBEDDER` | `openai` | Embedding provider. Valid values: `openai`, `fireworks` |

### OpenAI (default, recommended)

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | `""` | OpenAI API key. Also accepted as `CEREFOX_OPENAI_API_KEY`. Get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys). |
| `CEREFOX_OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL. Override for proxies or OpenAI-compatible providers. |
| `CEREFOX_OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model. |
| `CEREFOX_OPENAI_EMBEDDING_DIMENSIONS` | `768` | Output dimensions. Must match the database schema (VECTOR(768)). |

For cost estimates see `docs/guides/operational-cost.md`.

### Fireworks AI (alternative, lower cost)

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_FIREWORKS_API_KEY` | `""` | Fireworks AI API key. |
| `CEREFOX_FIREWORKS_BASE_URL` | `https://api.fireworks.ai/inference/v1` | Fireworks API base URL. |
| `CEREFOX_FIREWORKS_EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | Fireworks model. Must natively output 768-dim vectors. |

To use Fireworks:
```env
CEREFOX_EMBEDDER=fireworks
CEREFOX_FIREWORKS_API_KEY=fw_...
```

### Edge Functions (for agents)

The `cerefox-search` and `cerefox-ingest` Supabase Edge Functions handle embeddings server-side — agents don't need to set up any embedder locally. The Edge Functions read `OPENAI_API_KEY` from the Supabase project's secrets. See `docs/guides/connect-agents.md`.

---

## Chunking

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_MAX_CHUNK_CHARS` | `4000` | Maximum characters per chunk before splitting falls back to next heading level or paragraph |
| `CEREFOX_MIN_CHUNK_CHARS` | `100` | Minimum chunk size. Chunks smaller than this are merged into the previous chunk |
| `CEREFOX_OVERLAP_CHARS` | `200` | Character overlap added at paragraph-level splits (preserves context at boundaries). Not applied at heading boundaries — heading splits are clean. |

**Tuning advice:**
- Smaller `MAX_CHUNK_CHARS` → more precise chunk retrieval, but more DB rows and more embedding calls
- Larger `MAX_CHUNK_CHARS` → fewer chunks, coarser retrieval
- Default (4000) is a good balance for typical markdown notes
- `OVERLAP_CHARS` only has an effect when a section is long enough to require paragraph-level splitting

---

## Retrieval

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_MAX_RESPONSE_BYTES` | `65000` | Maximum bytes in a single search response. Set to Supabase MCP's limit by default. Reduce if using a custom MCP client with lower limits. |
| `CEREFOX_MIN_SEARCH_SCORE` | `0.50` | Minimum cosine similarity for hybrid and semantic search results (0.0–1.0). In **hybrid search**, chunks that matched the FTS keyword operator (`@@`) always pass through regardless of their vector score — the threshold only filters vector-only results. In **semantic search**, all results are filtered. The pure **FTS search** mode is unaffected. Increase for stricter precision; decrease for wider recall. |

**Score threshold guidance (OpenAI text-embedding-3-small):**

| Score | Meaning |
|-------|---------|
| 0.0 – 0.20 | Noise floor — unrelated content |
| 0.20 – 0.45 | Weak/tangential overlap — same domain, different topic |
| 0.45 – 0.70 | Genuine semantic match — related concepts, paraphrases |
| 0.70 – 1.0 | High similarity — near-duplicate or very direct answer |

Recommended values:
- `0.50` (default) — filters noise, keeps genuine results
- `0.40`–`0.45` — wider recall; useful for small corpora or exploratory search
- `0.70`–`0.80` — high precision; only very close semantic matches
- `0.0` — disable filtering entirely (returns all RPC results, not recommended)

---

## Storage & Backup

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_BACKUP_DIR` | `./backups` | Local directory where file system backups are stored. Created automatically if it doesn't exist. |

---

## Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_LOG_LEVEL` | `INFO` | Python logging level. Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |

Set to `DEBUG` during development to see detailed operation logs.

---

## Example: Minimal Production `.env`

```bash
# Required
CEREFOX_SUPABASE_URL=https://abcdefghijkl.supabase.co
CEREFOX_SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...

# Required for scripts only
CEREFOX_DATABASE_URL=postgresql://postgres.abcdefghijkl:MyPassword@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# Embeddings — OpenAI (default)
OPENAI_API_KEY=sk-...

# All other settings use defaults
```

## Example: Fireworks Embedder `.env`

```bash
CEREFOX_SUPABASE_URL=https://abcdefghijkl.supabase.co
CEREFOX_SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...
CEREFOX_DATABASE_URL=postgresql://...

CEREFOX_EMBEDDER=fireworks
CEREFOX_FIREWORKS_API_KEY=fw_...
```

---

## Changing the embedding model

Cerefox has **two independent access paths**, each with its own embedding configuration:

| Path | Where embedding happens | Config location |
|------|------------------------|-----------------|
| Local MCP server + CLI | Python `CloudEmbedder` | `.env` (`CEREFOX_OPENAI_EMBEDDING_MODEL`, etc.) |
| Edge Functions (GPT Actions, curl) | TypeScript constants in Edge Function code | Hardcoded in `supabase/functions/*/index.ts` |

When you change the embedding model, **both paths must be updated and kept in sync** — they must use the same model and dimensions, or search results will be incoherent (queries embedded by one model won't match chunks embedded by another).

### Step 1 — Update `.env`

Change `CEREFOX_OPENAI_EMBEDDING_MODEL` and `CEREFOX_OPENAI_EMBEDDING_DIMENSIONS` to the new values.

### Step 2 — Re-embed all stored chunks

```bash
uv run cerefox reindex
```

This re-embeds every chunk in the database using the model now configured in `.env`.
Preserves document IDs and project assignments. Run this before using the new model for searches.

### Step 3 — Update and redeploy the Edge Functions (if you use them)

The Edge Functions have the model hardcoded as TypeScript constants. Edit both files:

```
supabase/functions/cerefox-search/index.ts   (lines ~29–30)
supabase/functions/cerefox-ingest/index.ts   (lines ~25–26)
```

Change:
```typescript
const OPENAI_MODEL = "text-embedding-3-small";  // ← update this
const EMBEDDING_DIMENSIONS = 768;               // ← and this if dimensions change
```

Then redeploy via the Supabase CLI:
```bash
supabase functions deploy cerefox-search
supabase functions deploy cerefox-ingest
```

Or redeploy through the Supabase Dashboard → Edge Functions → Deploy.

> **If you only use the local MCP server** (Claude Desktop, ChatGPT Desktop, Cursor), Step 3 is
> optional — the Edge Functions are only used for GPT Actions and direct HTTP access.

> **Future improvement**: the Edge Functions will be updated to read model config from Supabase
> secrets, eliminating the need to edit TypeScript and redeploy when the model changes.

---

## Checking Your Configuration

Run the status script to verify everything is connected:

```bash
uv run python scripts/db_status.py
```

If it exits successfully (code 0), your configuration is correct.
