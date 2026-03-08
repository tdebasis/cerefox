# Quickstart — Zero to First Document in 15 Minutes

Get Cerefox running locally and ingest your first document.

---

## 1. Prerequisites (2 min)

- Python 3.11+ (`python3 --version`)
- `uv` package manager (`pip install uv`)
- A Supabase account — [supabase.com](https://supabase.com) (free tier works)

---

## 2. Install Cerefox (2 min)

```bash
git clone https://github.com/yourname/cerefox.git
cd cerefox
uv sync --extra mpnet
```

> `--extra mpnet` installs `sentence-transformers` for local embeddings (the default embedder). The model (~420 MB) downloads automatically on first use.

---

## 3. Set up Supabase (5 min)

1. Create a new Supabase project at [app.supabase.com](https://app.supabase.com).
2. Go to **Settings → API** and copy:
   - **Project URL** (looks like `https://abcd1234.supabase.co`)
   - **service_role** key (under "Project API keys" — use service_role, not anon)
3. Go to **Settings → Database** and copy the **Connection string** (URI format).

Create a `.env` file:

```env
CEREFOX_SUPABASE_URL=https://your-project-ref.supabase.co
CEREFOX_SUPABASE_KEY=your-service-role-key
CEREFOX_DATABASE_URL=postgresql://postgres:password@db.your-project-ref.supabase.co:5432/postgres
```

---

## 4. Deploy the schema (1 min)

```bash
uv run python scripts/db_deploy.py
```

You should see:
```
✓ Schema deployed successfully (4 tables, 5 functions, 2 indexes)
```

Verify:
```bash
uv run python scripts/db_status.py
```

---

## 5. Ingest your first document (2 min)

Have a markdown file? Ingest it:

```bash
uv run cerefox ingest my-notes.md
```

Or paste directly from the terminal:

```bash
echo "# My First Note

This is the beginning of my personal knowledge base." | uv run cerefox ingest --paste --title "First Note"
```

You'll see:
```
✓  Ingested: First Note
   Document ID : abc12345-...
   Chunks      : 1
   Total chars : 73
```

**First ingest downloads the embedding model (~420 MB). Subsequent ingests are instant.**

---

## 6. Start the web UI (30 sec)

```bash
uv run cerefox web
```

Open [http://localhost:8000](http://localhost:8000) — your dashboard is live.

---

## 7. Search your knowledge (30 sec)

From the CLI:

```bash
uv run cerefox search "my first note"
```

Or use the web UI at [http://localhost:8000/search](http://localhost:8000/search).

---

## 8. Connect an AI agent (optional, 3 min)

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "supabase": {
      "command": "npx",
      "args": [
        "-y",
        "@supabase/mcp-server-supabase@latest",
        "--supabase-url", "https://your-project-ref.supabase.co",
        "--supabase-key", "your-service-role-key"
      ]
    }
  }
}
```

Restart Claude Desktop. Ask Claude: *"Search my knowledge base for my first note using cerefox_hybrid_search."*

---

## You're done! 🎉

**What's next:**
- Ingest a directory of notes: `cerefox ingest-dir ./notes/ --recursive`
- Ingest a PDF: `cerefox ingest document.pdf` (requires `uv pip install pypdf`)
- Create a backup: `python scripts/backup_create.py`
- See all commands: `cerefox --help`

**More guides:**
- `docs/guides/setup-supabase.md` — detailed Supabase setup
- `docs/guides/configuration.md` — all configuration options
- `docs/guides/connect-agents.md` — connecting AI agents via MCP
- `docs/guides/setup-local.md` — local Docker setup (no Supabase account needed)
