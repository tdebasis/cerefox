# Cerefox - Project Guide

## What Is This

Cerefox is a personal "second brain" knowledge base. It stores markdown notes, thoughts, and ideas in Supabase (Postgres + pgvector), supports hybrid search (FTS + semantic), and exposes everything via MCP so any AI agent can query it.

Single-user, open-source (MIT), designed to be cheap/free to operate.

## Tech Stack

- **Language**: Python 3.11+
- **Database**: PostgreSQL 16+ with pgvector (Supabase free tier or local Docker)
- **Embeddings**: sentence-transformers (all-mpnet-base-v2, 768-dim) as default; Ollama models as upgrade path
- **Web framework**: FastAPI (API + web UI backend)
- **Web UI**: Jinja2 templates + HTMX (lightweight, no JS build step)
- **CLI**: Click
- **Package management**: uv (pyproject.toml)
- **Testing**: pytest
- **Linting**: ruff

## Project Structure

```
cerefox/
├── CLAUDE.md                  # This file
├── pyproject.toml
├── docs/
│   ├── requirements-and-specs.md  # Source of truth for requirements
│   ├── solution-design.md         # Architecture and design decisions
│   ├── plan.md                    # Implementation plan with progress
│   └── TODO.md                    # Backlog and future ideas
├── src/
│   └── cerefox/
│       ├── __init__.py
│       ├── config.py              # Settings via pydantic-settings
│       ├── db/
│       │   ├── schema.sql         # Database schema
│       │   ├── rpcs.sql           # Search RPC functions
│       │   └── client.py          # Supabase/Postgres client wrapper
│       ├── chunking/
│       │   ├── markdown.py        # Heading-aware MD splitter
│       │   └── converters.py      # PDF/DOCX → MD (future)
│       ├── embeddings/
│       │   ├── base.py            # Embedder protocol/interface
│       │   ├── mpnet.py           # all-mpnet-base-v2
│       │   └── ollama_embed.py    # Ollama embedding models
│       ├── ingestion/
│       │   └── pipeline.py        # Ingest documents → chunks → DB
│       ├── retrieval/
│       │   └── search.py          # Search + small-to-big assembly
│       ├── backup/
│       │   └── fs_backup.py       # File system / git backup
│       ├── api/
│       │   ├── app.py             # FastAPI application
│       │   └── routes.py          # API endpoints
│       └── cli.py                 # CLI entry point
├── web/
│   └── templates/                 # Jinja2 templates for web UI
├── scripts/
│   ├── db_deploy.py           # Deploy schema to Supabase/Postgres
│   ├── db_migrate.py          # Apply schema migrations
│   ├── backup_create.py       # Take a local backup of the knowledge base
│   └── backup_restore.py      # Restore from a backup
├── tests/
│   ├── chunking/
│   ├── embeddings/
│   ├── ingestion/
│   ├── retrieval/
│   └── conftest.py
├── docker-compose.yml
└── Dockerfile
```

## Development Conventions

### Code Style
- Use ruff for linting and formatting (line length 100)
- Type hints on all public functions
- Docstrings only where the purpose isn't obvious from the name/signature
- Prefer simple, flat code over abstractions — don't create a helper for something used once

### Naming
- Database tables: `cerefox_` prefix (e.g., `cerefox_documents`, `cerefox_chunks`)
- Database RPCs: `cerefox_` prefix (e.g., `cerefox_hybrid_search`)
- Python modules: snake_case, short names
- Config: environment variables with `CEREFOX_` prefix

### Architecture Principles
- **Pluggable embedders**: all embedders implement the `Embedder` protocol (see `embeddings/base.py`)
- **Markdown-first**: all content is converted to markdown before chunking/storage
- **Fire-and-forget ingestion**: ingestion can be async; failures log errors but don't block
- **Parameterized limits**: response size limits, chunk sizes, etc. are configurable via settings
- **Two-table design**: `cerefox_documents` (document-level) + `cerefox_chunks` (chunk-level) for clean separation

### Configuration
- Use pydantic-settings with `.env` file support
- All config has sensible defaults for local development
- Key settings: `CEREFOX_SUPABASE_URL`, `CEREFOX_SUPABASE_KEY`, `CEREFOX_EMBEDDER`, `CEREFOX_MAX_RESPONSE_BYTES`

### Testing
- **Write tests alongside code, not after** — every module added to `src/cerefox/` gets a corresponding test module in `tests/`
- Run tests: `uv run pytest`
- Tests go in `tests/` mirroring `src/cerefox/` structure (e.g., `tests/chunking/test_markdown.py`)
- Use fixtures for DB client mocking — never hit a real database in unit tests
- Integration tests that need Supabase are marked `@pytest.mark.integration` and skipped by default
- Test at least: happy path, edge cases (empty input, max size, malformed input), error conditions

### Git
- Main branch: `main`
- Commit messages: imperative mood, concise (e.g., "Add markdown chunking engine")
- No force pushes to main

## Key Design Decisions

1. **Two-table schema** (documents + chunks) instead of single flat table — enables clean document lifecycle management and small-to-big retrieval
2. **768-dim vectors** standardized across all embedders — choose models that output 768 dims or use dimensionality reduction
3. **JSONB metadata** on both documents and chunks — evolvable without schema changes
4. **Heading-based chunking** (H1 > H2 > H3 fallback) — preserves semantic coherence
5. **Supabase MCP as primary access layer** — agents call RPCs directly, no custom MCP server needed initially

## Documentation as Source of Truth

The project documentation is a first-class artifact — kept accurate and current at all times.

| File | Owner | Update When |
|------|-------|-------------|
| `docs/requirements-and-specs.md` | Requirements | A requirement changes or is added/removed |
| `docs/solution-design.md` | Architecture | A design decision is made or revised |
| `docs/plan.md` | Progress | A task starts, completes, or is re-scoped |
| `docs/TODO.md` | Backlog | A new idea or future task surfaces |
| `CLAUDE.md` | Conventions | Project conventions or structure changes |

**Rule**: when implementing a feature, update the relevant docs in the same commit/session. Another developer or AI agent should be able to read these files at any point and have an accurate picture of what is built, what is planned, and why.

## Quick Reference

- **Docs**: `docs/plan.md` for current status, `docs/TODO.md` for backlog
- **Schema**: `src/cerefox/db/schema.sql`
- **Config**: `.env` file or environment variables (see `src/cerefox/config.py`)
- **Max response size**: defaults to 65000 bytes (Supabase MCP limit), configurable via `CEREFOX_MAX_RESPONSE_BYTES`
