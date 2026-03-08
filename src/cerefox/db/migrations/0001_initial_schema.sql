-- Migration: 0001_initial_schema
-- Applied by: python scripts/db_migrate.py
-- Creates the full initial Cerefox schema including tables, indexes, triggers, and RPCs.
--
-- This file is the canonical record of the initial database state.
-- Subsequent changes go in 0002_..., 0003_..., etc.
-- db_migrate.py tracks applied migrations in cerefox_migrations table.

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ── Tables ────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cerefox_projects (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    description TEXT,
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cerefox_projects_name_unique UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS cerefox_documents (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT        NOT NULL,
    source       TEXT        NOT NULL DEFAULT 'manual',
    source_path  TEXT,
    content_hash TEXT        NOT NULL,
    project_id   UUID        REFERENCES cerefox_projects(id) ON DELETE SET NULL,
    metadata     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    chunk_count  INT         NOT NULL DEFAULT 0,
    total_chars  INT         NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cerefox_documents_hash_unique UNIQUE (content_hash)
);

CREATE TABLE IF NOT EXISTS cerefox_chunks (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id        UUID        NOT NULL REFERENCES cerefox_documents(id) ON DELETE CASCADE,
    chunk_index        INT         NOT NULL,
    heading_path       TEXT[]      NOT NULL DEFAULT '{}',
    heading_level      INT,
    title              TEXT,
    content            TEXT        NOT NULL,
    char_count         INT         NOT NULL,
    embedding_primary  VECTOR(768) NOT NULL,
    embedding_upgrade  VECTOR(768),
    embedder_primary   TEXT        NOT NULL DEFAULT 'all-mpnet-base-v2',
    embedder_upgrade   TEXT,
    fts TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
        setweight(to_tsvector('english', content), 'B')
    ) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT cerefox_chunks_doc_idx_unique UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS cerefox_migrations (
    id         SERIAL      PRIMARY KEY,
    filename   TEXT        NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_fts
    ON cerefox_chunks USING GIN(fts);

CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_emb_primary
    ON cerefox_chunks USING hnsw (embedding_primary vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_emb_upgrade
    ON cerefox_chunks USING hnsw (embedding_upgrade vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_cerefox_chunks_document
    ON cerefox_chunks(document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_cerefox_docs_metadata
    ON cerefox_documents USING GIN(metadata);

CREATE INDEX IF NOT EXISTS idx_cerefox_docs_project
    ON cerefox_documents(project_id);

CREATE INDEX IF NOT EXISTS idx_cerefox_docs_hash
    ON cerefox_documents(content_hash);

-- ── Triggers ──────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION cerefox_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trig_cerefox_projects_updated
    BEFORE UPDATE ON cerefox_projects
    FOR EACH ROW EXECUTE FUNCTION cerefox_set_updated_at();

CREATE OR REPLACE TRIGGER trig_cerefox_documents_updated
    BEFORE UPDATE ON cerefox_documents
    FOR EACH ROW EXECUTE FUNCTION cerefox_set_updated_at();

CREATE OR REPLACE TRIGGER trig_cerefox_chunks_updated
    BEFORE UPDATE ON cerefox_chunks
    FOR EACH ROW EXECUTE FUNCTION cerefox_set_updated_at();

-- ── RPCs ──────────────────────────────────────────────────────────────────────
-- (Included verbatim from rpcs.sql — kept in sync manually.)

CREATE OR REPLACE FUNCTION cerefox_hybrid_search(
    p_query_text      TEXT,
    p_query_embedding VECTOR(768),
    p_match_count     INT     DEFAULT 10,
    p_alpha           FLOAT   DEFAULT 0.7,
    p_use_upgrade     BOOLEAN DEFAULT FALSE,
    p_project_id      UUID    DEFAULT NULL
)
RETURNS TABLE (
    chunk_id UUID, document_id UUID, chunk_index INT, title TEXT, content TEXT,
    heading_path TEXT[], heading_level INT, score FLOAT,
    doc_title TEXT, doc_source TEXT, doc_project_id UUID, doc_metadata JSONB
)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    query_fts tsquery := websearch_to_tsquery('english', p_query_text);
    candidate_count INT := p_match_count * 5;
BEGIN
    RETURN QUERY
    WITH
        fts_results AS (
            SELECT c.id, ts_rank_cd(c.fts, query_fts)::FLOAT AS fts_score
            FROM cerefox_chunks c
            JOIN cerefox_documents d ON c.document_id = d.id
            WHERE c.fts @@ query_fts AND (p_project_id IS NULL OR d.project_id = p_project_id)
            ORDER BY fts_score DESC LIMIT candidate_count
        ),
        vec_results AS (
            SELECT c.id,
                CASE WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
                    THEN (1.0 - (c.embedding_upgrade <=> p_query_embedding))::FLOAT
                    ELSE (1.0 - (c.embedding_primary <=> p_query_embedding))::FLOAT
                END AS vec_score
            FROM cerefox_chunks c
            JOIN cerefox_documents d ON c.document_id = d.id
            WHERE (p_project_id IS NULL OR d.project_id = p_project_id)
            ORDER BY CASE WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
                THEN c.embedding_upgrade <=> p_query_embedding
                ELSE c.embedding_primary <=> p_query_embedding END
            LIMIT candidate_count
        ),
        combined AS (
            SELECT COALESCE(f.id, v.id) AS id,
                (p_alpha * COALESCE(v.vec_score, 0.0) + (1.0 - p_alpha) * COALESCE(f.fts_score, 0.0)) AS score
            FROM fts_results f FULL OUTER JOIN vec_results v ON f.id = v.id
        )
    SELECT c.id, c.document_id, c.chunk_index, c.title, c.content, c.heading_path, c.heading_level,
        cm.score, d.title, d.source, d.project_id, d.metadata
    FROM combined cm
    JOIN cerefox_chunks c ON c.id = cm.id
    JOIN cerefox_documents d ON c.document_id = d.id
    ORDER BY cm.score DESC LIMIT p_match_count;
END;
$$;

CREATE OR REPLACE FUNCTION cerefox_fts_search(
    p_query_text  TEXT,
    p_match_count INT  DEFAULT 10,
    p_project_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    chunk_id UUID, document_id UUID, chunk_index INT, title TEXT, content TEXT,
    heading_path TEXT[], heading_level INT, score FLOAT,
    doc_title TEXT, doc_source TEXT, doc_project_id UUID, doc_metadata JSONB
)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    query_fts tsquery := websearch_to_tsquery('english', p_query_text);
BEGIN
    RETURN QUERY
    SELECT c.id, c.document_id, c.chunk_index, c.title, c.content, c.heading_path, c.heading_level,
        ts_rank_cd(c.fts, query_fts)::FLOAT, d.title, d.source, d.project_id, d.metadata
    FROM cerefox_chunks c
    JOIN cerefox_documents d ON c.document_id = d.id
    WHERE c.fts @@ query_fts AND (p_project_id IS NULL OR d.project_id = p_project_id)
    ORDER BY ts_rank_cd(c.fts, query_fts) DESC
    LIMIT p_match_count;
END;
$$;

CREATE OR REPLACE FUNCTION cerefox_semantic_search(
    p_query_embedding VECTOR(768),
    p_match_count     INT     DEFAULT 10,
    p_use_upgrade     BOOLEAN DEFAULT FALSE,
    p_project_id      UUID    DEFAULT NULL
)
RETURNS TABLE (
    chunk_id UUID, document_id UUID, chunk_index INT, title TEXT, content TEXT,
    heading_path TEXT[], heading_level INT, score FLOAT,
    doc_title TEXT, doc_source TEXT, doc_project_id UUID, doc_metadata JSONB
)
LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    RETURN QUERY
    SELECT c.id, c.document_id, c.chunk_index, c.title, c.content, c.heading_path, c.heading_level,
        CASE WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
            THEN (1.0 - (c.embedding_upgrade <=> p_query_embedding))::FLOAT
            ELSE (1.0 - (c.embedding_primary <=> p_query_embedding))::FLOAT
        END AS score,
        d.title, d.source, d.project_id, d.metadata
    FROM cerefox_chunks c
    JOIN cerefox_documents d ON c.document_id = d.id
    WHERE (p_project_id IS NULL OR d.project_id = p_project_id)
      AND (p_use_upgrade = FALSE OR c.embedding_upgrade IS NOT NULL)
    ORDER BY CASE WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
        THEN c.embedding_upgrade <=> p_query_embedding
        ELSE c.embedding_primary <=> p_query_embedding END
    LIMIT p_match_count;
END;
$$;

CREATE OR REPLACE FUNCTION cerefox_reconstruct_doc(p_document_id UUID)
RETURNS TABLE (
    document_id UUID, doc_title TEXT, doc_source TEXT, doc_metadata JSONB,
    full_content TEXT, chunk_count INT, total_chars INT
)
LANGUAGE sql SECURITY DEFINER STABLE AS $$
    SELECT d.id, d.title, d.source, d.metadata,
        STRING_AGG(c.content, E'\n\n' ORDER BY c.chunk_index),
        COUNT(*)::INT, SUM(c.char_count)::INT
    FROM cerefox_documents d
    JOIN cerefox_chunks c ON c.document_id = d.id
    WHERE d.id = p_document_id
    GROUP BY d.id, d.title, d.source, d.metadata;
$$;
