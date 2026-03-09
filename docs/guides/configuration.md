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

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREFOX_EMBEDDER` | `mpnet` | Which embedder to use for new ingestions. Valid values: `mpnet`, `ollama` |
| `CEREFOX_OLLAMA_URL` | `http://localhost:11434` | Ollama server base URL. Only used when `CEREFOX_EMBEDDER=ollama` |
| `CEREFOX_OLLAMA_MODEL` | `nomic-embed-text` | Ollama model name for embeddings. Must produce 768-dim vectors. Only used when `CEREFOX_EMBEDDER=ollama` |

### Embedder Notes

**`mpnet`** (default):
- Uses `sentence-transformers/all-mpnet-base-v2`
- Runs locally, no API cost
- First run downloads the model (~420MB); cached after that
- Output: 768-dim normalized vectors

**`ollama`**:
- Requires [Ollama](https://ollama.ai) running locally or on a server
- Recommended models: `nomic-embed-text` (768-dim), `mxbai-embed-large` (1024-dim, will require dimensionality reduction in future)
- Pull a model first: `ollama pull nomic-embed-text`

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
| `CEREFOX_MIN_SEARCH_SCORE` | `0.65` | Minimum cosine similarity for hybrid and semantic search results (0.0–1.0). In **hybrid search**, chunks that matched the FTS keyword operator (`@@`) always pass through regardless of their vector score — the threshold only filters vector-only results. In **semantic search**, all results are filtered. The pure **FTS search** mode is unaffected. Increase for stricter precision; decrease for wider recall. |

**Score threshold guidance (all-mpnet-base-v2):**

Sentence-transformer cosine scores are **not** percentage-of-similarity. The score distribution for `all-mpnet-base-v2` is:

| Score | Meaning |
|-------|---------|
| 0.0 – 0.35 | Noise floor — even unrelated sentences land here |
| 0.35 – 0.55 | Weak/tangential overlap — same domain, different topic |
| 0.55 – 0.75 | Genuine semantic match — related concepts, paraphrases |
| 0.75 – 1.0 | High similarity — near-duplicate or very direct answer |

Recommended values:
- `0.65` (default) — filters noise and weak matches, keeps genuine results
- `0.55`–`0.60` — wider recall; useful for small corpora or exploratory search
- `0.75`–`0.80` — high precision; only very close semantic matches
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

# Embeddings — local default, no API cost
CEREFOX_EMBEDDER=mpnet

# All other settings use defaults
```

## Example: Ollama Embedder `.env`

```bash
CEREFOX_SUPABASE_URL=https://abcdefghijkl.supabase.co
CEREFOX_SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...
CEREFOX_DATABASE_URL=postgresql://...

CEREFOX_EMBEDDER=ollama
CEREFOX_OLLAMA_URL=http://localhost:11434
CEREFOX_OLLAMA_MODEL=nomic-embed-text
```

Ensure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull nomic-embed-text`) before ingesting.

---

## Checking Your Configuration

Run the status script to verify everything is connected:

```bash
python scripts/db_status.py
```

If it exits successfully (code 0), your configuration is correct.
