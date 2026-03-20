-- Migration 0003: Add document versioning support
-- Applied by: scripts/db_migrate.py
-- Safe to apply on a live database with existing documents and chunks.
-- All changes are additive — no data is dropped or altered.
--
-- What this migration does:
--   1. Creates cerefox_document_versions table
--   2. Adds nullable version_id FK to cerefox_chunks
--   3. Drops the plain UNIQUE constraint on (document_id, chunk_index)
--   4. Adds a partial unique index on (document_id, chunk_index) WHERE version_id IS NULL
--   5. Drops the plain HNSW and GIN indexes (replaced by partial equivalents)
--   6. Creates partial HNSW, GIN, and version-lookup indexes
--   7. Enables RLS on cerefox_document_versions

-- ── 1. Document versions table ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cerefox_document_versions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID        NOT NULL REFERENCES cerefox_documents(id) ON DELETE CASCADE,
    version_number  INT         NOT NULL,
    source          TEXT        NOT NULL DEFAULT 'manual',
    chunk_count     INT         NOT NULL DEFAULT 0,
    total_chars     INT         NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT cerefox_document_versions_doc_num_unique UNIQUE (document_id, version_number)
);

-- ── 2. Add version_id to chunks ────────────────────────────────────────────
-- NULL = current version (searchable, indexed)
-- non-NULL = archived under that version (not searchable, lazily deleted)

ALTER TABLE cerefox_chunks
    ADD COLUMN IF NOT EXISTS version_id UUID
        REFERENCES cerefox_document_versions(id) ON DELETE CASCADE;

-- ── 3. Drop plain unique constraint ────────────────────────────────────────
-- The old constraint disallows duplicate (document_id, chunk_index) across ALL
-- chunks. With versioning, the same chunk_index can exist in both current and
-- archived versions. The partial unique index below replaces this constraint.

ALTER TABLE cerefox_chunks
    DROP CONSTRAINT IF EXISTS cerefox_chunks_doc_idx_unique;

-- ── 4. Partial unique index for current chunks ──────────────────────────────
-- Ensures (document_id, chunk_index) is unique among current chunks (version_id IS NULL).
-- Archived chunks are excluded and may share chunk_index values across versions.

CREATE UNIQUE INDEX IF NOT EXISTS idx_cerefox_chunks_current_unique
    ON cerefox_chunks(document_id, chunk_index)
    WHERE version_id IS NULL;

-- ── 5. Drop plain indexes (replaced by partial equivalents below) ───────────

DROP INDEX IF EXISTS idx_cerefox_chunks_fts;
DROP INDEX IF EXISTS idx_cerefox_chunks_emb_primary;
DROP INDEX IF EXISTS idx_cerefox_chunks_emb_upgrade;

-- ── 6. Partial FTS, HNSW, and version-lookup indexes ───────────────────────
-- WHERE version_id IS NULL ensures only current chunks are indexed for search.
-- Archived chunks are never returned in search results.

-- Full-text search (current chunks only)
CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_fts
    ON cerefox_chunks USING GIN(fts)
    WHERE version_id IS NULL;

-- Primary vector index (current chunks only)
CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_emb_primary
    ON cerefox_chunks USING hnsw (embedding_primary vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE version_id IS NULL;

-- Upgrade vector index (current chunks only)
CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_emb_upgrade
    ON cerefox_chunks USING hnsw (embedding_upgrade vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE version_id IS NULL;

-- Archived chunk lookup (for version retrieval)
CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_version
    ON cerefox_chunks(version_id, chunk_index)
    WHERE version_id IS NOT NULL;

-- ── 7. RLS on new table ────────────────────────────────────────────────────

ALTER TABLE cerefox_document_versions ENABLE ROW LEVEL SECURITY;

-- ── 8. updated_at trigger on versions table ────────────────────────────────
-- cerefox_document_versions has no updated_at column (immutable after creation),
-- so no trigger is needed.
