# Setting Up Cerefox with Supabase

This guide walks you from a blank Supabase project to a fully deployed Cerefox schema, ready to ingest documents and serve AI agents via MCP.

**Time required**: ~15 minutes

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- A Supabase account (free tier is enough): [supabase.com](https://supabase.com)
- Python 3.11 or higher

---

## Step 1 — Create a Supabase Project

1. Go to [app.supabase.com](https://app.supabase.com) and sign in
2. Click **New project**
3. Choose a name (e.g. `cerefox`), set a strong database password, pick a region close to you
4. Click **Create new project** and wait ~2 minutes for it to provision

---

## Step 2 — Enable the pgvector Extension

Supabase includes pgvector but you need to activate it:

1. In your project dashboard, go to **Database → Extensions**
2. Search for `vector` and enable it

The deploy script also runs `CREATE EXTENSION IF NOT EXISTS vector` automatically, but enabling it in the UI first prevents permission issues.

---

## Step 3 — Collect Your Credentials

You need three values from Supabase. Find them as follows:

### API URL and Service Role Key
1. Go to **Project Settings → API**
2. Copy:
   - **Project URL** → `CEREFOX_SUPABASE_URL`
   - **service_role** key (under "Project API keys") → `CEREFOX_SUPABASE_KEY`

> ⚠️ Use the **service_role** key (not the anon key). The service role key bypasses Row Level Security and is needed for schema-level operations. Keep it secret — never commit it to git.

### Direct Database URL (for deployment scripts)
1. Go to **Project Settings → Database**
2. Under **Connection string**, select the **URI** tab
3. Copy the connection string — it looks like:
   ```
   postgresql://postgres.PROJECTREF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
   ```
   Replace `[YOUR-PASSWORD]` with the password you set in Step 1.

---

## Step 4 — Configure Your Environment

```bash
# In the cerefox project root:
cp .env.example .env
```

Edit `.env` and fill in your three values:

```bash
CEREFOX_SUPABASE_URL=https://your-project-ref.supabase.co
CEREFOX_SUPABASE_KEY=eyJhbGc...your-service-role-key
CEREFOX_DATABASE_URL=postgresql://postgres.yourref:yourpassword@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

Leave all other settings at their defaults for now.

---

## Step 5 — Install Dependencies

```bash
uv sync
```

This installs all Python dependencies defined in `pyproject.toml`, including `supabase`, `psycopg2-binary`, and `pydantic-settings`.

---

## Step 6 — Deploy the Schema

```bash
# Preview what will happen (no changes made):
python scripts/db_deploy.py --dry-run

# Apply the schema:
python scripts/db_deploy.py
```

Expected output:
```
╔══════════════════════════════════════╗
║  Cerefox DB Deploy                   ║
╚══════════════════════════════════════╝

Connecting to database...

▶  Enable extensions (uuid-ossp, vector/pgvector)...
   ✓  Done

▶  Apply schema (tables, indexes, triggers)...
   ✓  Done

▶  Apply RPCs (search functions)...
   ✓  Done

──────────────────────────────────────────
✓  Deployment complete. 3 steps applied.

Next step: verify the schema with:
    python scripts/db_status.py
```

---

## Step 7 — Verify the Schema

```bash
python scripts/db_status.py
```

Expected output:
```
╔══════════════════════════════════════╗
║  Cerefox DB Status                   ║
╚══════════════════════════════════════╝

Extensions:
  ✓  uuid-ossp
  ✓  vector

Tables:
  ✓  cerefox_projects
  ✓  cerefox_documents
  ✓  cerefox_chunks
  ✓  cerefox_migrations

Functions / RPCs:
  ✓  cerefox_set_updated_at()
  ✓  cerefox_hybrid_search()
  ✓  cerefox_fts_search()
  ✓  cerefox_semantic_search()
  ✓  cerefox_reconstruct_doc()
  ✓  cerefox_save_note()
  ✓  cerefox_search_docs()
  ✓  cerefox_context_expand()

Indexes:
  ✓  idx_cerefox_chunks_fts
  ✓  idx_cerefox_chunks_emb_primary
  ✓  idx_cerefox_chunks_emb_upgrade
  ✓  idx_cerefox_chunks_document
  ✓  idx_cerefox_docs_metadata
  ✓  idx_cerefox_docs_project

Row counts:
  ℹ  cerefox_projects: 0 rows
  ℹ  cerefox_documents: 0 rows
  ℹ  cerefox_chunks: 0 rows

──────────────────────────────────────────
✓  All checks passed. Schema looks healthy.
```

All checks should show ✓. If any show ✗, re-run `python scripts/db_deploy.py`.

---

## Step 8 — Run the Tests

Confirm everything is wired up correctly:

```bash
uv run pytest
```

These are unit tests only (no real database connection needed). You should see all tests pass.

To also run the integration tests against your live Supabase instance:
```bash
uv run pytest -m integration
```

---

## Step 9 — Connect to Supabase MCP (optional, for agents)

Once documents are ingested, AI agents can search Cerefox via the Supabase MCP server.

1. In your Supabase project, go to **Project Settings → Integrations → MCP**
2. Enable the MCP server
3. Copy the MCP endpoint URL and token

Then configure your agent. See `docs/guides/connect-agents.md` for Claude, Cursor, and generic MCP client setup.

---

## Troubleshooting

### "could not connect to server"
- Check that `CEREFOX_DATABASE_URL` is correct and the password doesn't contain special characters that need URL-encoding
- Try pasting the URL directly into `psql` to verify it works

### "extension 'vector' does not exist"
- Go to Supabase Dashboard → Database → Extensions → enable `vector`
- Then re-run `python scripts/db_deploy.py`

### "permission denied for table"
- Make sure you're using the **service_role** key, not the anon key

### Schema already exists (re-deploying)
- All schema objects use `CREATE ... IF NOT EXISTS` / `CREATE OR REPLACE`, so re-running is safe
- To start completely fresh: `python scripts/db_deploy.py --reset` (⚠️ deletes all data)
