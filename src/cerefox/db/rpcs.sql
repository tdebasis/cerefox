-- Cerefox Search & Retrieval RPCs
-- These functions are exposed as MCP tools via Supabase.
-- Run via: python scripts/db_deploy.py (after schema.sql)
--
-- All RPCs are SECURITY DEFINER so they can be called safely via the
-- Supabase anon/service key without exposing the underlying tables directly.

-- ── Shared return type columns ────────────────────────────────────────────────
-- All search RPCs return the same shape for consistency:
--   chunk_id, document_id, chunk_index, title, content, heading_path,
--   heading_level, score, doc_title, doc_source, doc_project_id, doc_metadata

-- ── Hybrid Search ─────────────────────────────────────────────────────────────
-- Combines full-text search (FTS) and vector similarity with a configurable
-- alpha weight. alpha=1.0 means pure semantic; alpha=0.0 means pure FTS.
--
-- V1 approach: run both searches (top N*5 candidates each), FULL OUTER JOIN on
-- chunk ID, then combine scores with weighted average. Simple and fast for
-- typical knowledge base sizes.

CREATE OR REPLACE FUNCTION cerefox_hybrid_search(
    p_query_text      TEXT,
    p_query_embedding VECTOR(768),
    p_match_count     INT     DEFAULT 10,
    p_alpha           FLOAT   DEFAULT 0.7,
    p_use_upgrade     BOOLEAN DEFAULT FALSE,
    p_project_id      UUID    DEFAULT NULL
)
RETURNS TABLE (
    chunk_id      UUID,
    document_id   UUID,
    chunk_index   INT,
    title         TEXT,
    content       TEXT,
    heading_path  TEXT[],
    heading_level INT,
    score         FLOAT,
    doc_title     TEXT,
    doc_source    TEXT,
    doc_project_id UUID,
    doc_metadata  JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    query_fts tsquery := websearch_to_tsquery('english', p_query_text);
    candidate_count INT := p_match_count * 5;
BEGIN
    RETURN QUERY
    WITH
        fts_results AS (
            SELECT
                c.id,
                ts_rank_cd(c.fts, query_fts)::FLOAT AS fts_score
            FROM cerefox_chunks c
            JOIN cerefox_documents d ON c.document_id = d.id
            WHERE c.fts @@ query_fts
              AND (p_project_id IS NULL OR d.project_id = p_project_id)
            ORDER BY fts_score DESC
            LIMIT candidate_count
        ),
        vec_results AS (
            SELECT
                c.id,
                CASE
                    WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
                        THEN (1.0 - (c.embedding_upgrade <=> p_query_embedding))::FLOAT
                    ELSE
                        (1.0 - (c.embedding_primary <=> p_query_embedding))::FLOAT
                END AS vec_score
            FROM cerefox_chunks c
            JOIN cerefox_documents d ON c.document_id = d.id
            WHERE (p_project_id IS NULL OR d.project_id = p_project_id)
            ORDER BY
                CASE
                    WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
                        THEN c.embedding_upgrade <=> p_query_embedding
                    ELSE c.embedding_primary <=> p_query_embedding
                END
            LIMIT candidate_count
        ),
        combined AS (
            SELECT
                COALESCE(f.id, v.id) AS id,
                (   p_alpha * COALESCE(v.vec_score, 0.0) +
                    (1.0 - p_alpha) * COALESCE(f.fts_score, 0.0)
                ) AS score
            FROM fts_results f
            FULL OUTER JOIN vec_results v ON f.id = v.id
        )
    SELECT
        c.id            AS chunk_id,
        c.document_id,
        c.chunk_index,
        c.title,
        c.content,
        c.heading_path,
        c.heading_level,
        cm.score,
        d.title         AS doc_title,
        d.source        AS doc_source,
        d.project_id    AS doc_project_id,
        d.metadata      AS doc_metadata
    FROM combined cm
    JOIN cerefox_chunks   c ON c.id = cm.id
    JOIN cerefox_documents d ON c.document_id = d.id
    ORDER BY cm.score DESC
    LIMIT p_match_count;
END;
$$;

-- ── FTS-Only Search ───────────────────────────────────────────────────────────
-- Pure keyword / exact-match search. Best for names, dates, tags.

CREATE OR REPLACE FUNCTION cerefox_fts_search(
    p_query_text  TEXT,
    p_match_count INT  DEFAULT 10,
    p_project_id  UUID DEFAULT NULL
)
RETURNS TABLE (
    chunk_id      UUID,
    document_id   UUID,
    chunk_index   INT,
    title         TEXT,
    content       TEXT,
    heading_path  TEXT[],
    heading_level INT,
    score         FLOAT,
    doc_title     TEXT,
    doc_source    TEXT,
    doc_project_id UUID,
    doc_metadata  JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    query_fts tsquery := websearch_to_tsquery('english', p_query_text);
BEGIN
    RETURN QUERY
    SELECT
        c.id            AS chunk_id,
        c.document_id,
        c.chunk_index,
        c.title,
        c.content,
        c.heading_path,
        c.heading_level,
        ts_rank_cd(c.fts, query_fts)::FLOAT AS score,
        d.title         AS doc_title,
        d.source        AS doc_source,
        d.project_id    AS doc_project_id,
        d.metadata      AS doc_metadata
    FROM cerefox_chunks c
    JOIN cerefox_documents d ON c.document_id = d.id
    WHERE c.fts @@ query_fts
      AND (p_project_id IS NULL OR d.project_id = p_project_id)
    ORDER BY score DESC
    LIMIT p_match_count;
END;
$$;

-- ── Semantic-Only Search ──────────────────────────────────────────────────────
-- Pure vector similarity. Best for conceptual / paraphrase queries.

CREATE OR REPLACE FUNCTION cerefox_semantic_search(
    p_query_embedding VECTOR(768),
    p_match_count     INT     DEFAULT 10,
    p_use_upgrade     BOOLEAN DEFAULT FALSE,
    p_project_id      UUID    DEFAULT NULL
)
RETURNS TABLE (
    chunk_id      UUID,
    document_id   UUID,
    chunk_index   INT,
    title         TEXT,
    content       TEXT,
    heading_path  TEXT[],
    heading_level INT,
    score         FLOAT,
    doc_title     TEXT,
    doc_source    TEXT,
    doc_project_id UUID,
    doc_metadata  JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id            AS chunk_id,
        c.document_id,
        c.chunk_index,
        c.title,
        c.content,
        c.heading_path,
        c.heading_level,
        CASE
            WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
                THEN (1.0 - (c.embedding_upgrade <=> p_query_embedding))::FLOAT
            ELSE
                (1.0 - (c.embedding_primary <=> p_query_embedding))::FLOAT
        END AS score,
        d.title         AS doc_title,
        d.source        AS doc_source,
        d.project_id    AS doc_project_id,
        d.metadata      AS doc_metadata
    FROM cerefox_chunks c
    JOIN cerefox_documents d ON c.document_id = d.id
    WHERE (p_project_id IS NULL OR d.project_id = p_project_id)
      AND (p_use_upgrade = FALSE OR c.embedding_upgrade IS NOT NULL)
    ORDER BY
        CASE
            WHEN p_use_upgrade AND c.embedding_upgrade IS NOT NULL
                THEN c.embedding_upgrade <=> p_query_embedding
            ELSE c.embedding_primary <=> p_query_embedding
        END
    LIMIT p_match_count;
END;
$$;

-- ── Document Reconstruction ───────────────────────────────────────────────────
-- Reassemble a full document from its chunks (ordered by chunk_index).
-- Agents use this after a chunk-level search to get broader context.

CREATE OR REPLACE FUNCTION cerefox_reconstruct_doc(
    p_document_id UUID
)
RETURNS TABLE (
    document_id  UUID,
    doc_title    TEXT,
    doc_source   TEXT,
    doc_metadata JSONB,
    full_content TEXT,
    chunk_count  INT,
    total_chars  INT
)
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT
        d.id            AS document_id,
        d.title         AS doc_title,
        d.source        AS doc_source,
        d.metadata      AS doc_metadata,
        STRING_AGG(c.content, E'\n\n' ORDER BY c.chunk_index) AS full_content,
        COUNT(*)::INT   AS chunk_count,
        SUM(c.char_count)::INT AS total_chars
    FROM cerefox_documents d
    JOIN cerefox_chunks c ON c.document_id = d.id
    WHERE d.id = p_document_id
    GROUP BY d.id, d.title, d.source, d.metadata;
$$;
