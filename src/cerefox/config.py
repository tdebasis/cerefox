"""Cerefox configuration via pydantic-settings.

All settings are read from environment variables with the CEREFOX_ prefix,
or from a .env file in the working directory. See .env.example for reference.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CEREFOX_",
        env_file=".env",
        env_file_encoding="utf-8",
        # Don't raise if .env doesn't exist
        env_ignore_empty=False,
        extra="ignore",
    )

    # ── Supabase ──────────────────────────────────────────────────────────────
    # API URL and service role key — used by the application (supabase-py)
    supabase_url: str = ""
    supabase_key: str = ""

    # Direct Postgres connection URL — used by deployment scripts (psycopg2)
    database_url: str = ""

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedder: Literal["mpnet", "ollama"] = "mpnet"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"
    vector_dimensions: int = 768

    # ── Chunking ──────────────────────────────────────────────────────────────
    max_chunk_chars: int = 4000
    min_chunk_chars: int = 100
    overlap_chars: int = 200

    # ── Retrieval ─────────────────────────────────────────────────────────────
    max_response_bytes: int = 65000
    # Minimum cosine similarity score for hybrid and semantic search results (0.0–1.0).
    # Results with a vector similarity below this threshold are dropped before returning.
    # FTS results are not affected (ts_rank_cd scores are on a different scale).
    #
    # NOTE: sentence-transformer cosine scores are NOT percentage-of-similarity.
    # For all-mpnet-base-v2, 0.0–0.35 is the noise floor (even unrelated sentences
    # land here). Genuine semantic matches typically score 0.55+. 0.65 is a good
    # default — raise toward 0.80 for stricter precision, lower to 0.50 for recall.
    min_search_score: float = 0.65

    # ── Metadata ──────────────────────────────────────────────────────────────
    # When True, ingestion rejects metadata keys not registered in
    # cerefox_metadata_keys.  Set to False to allow any key (log-and-ignore
    # for unknown keys when False, raise ValueError when True).
    metadata_strict: bool = True

    # ── Storage ───────────────────────────────────────────────────────────────
    backup_dir: str = "./backups"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    def is_supabase_configured(self) -> bool:
        """Return True if Supabase API credentials are set."""
        return bool(self.supabase_url and self.supabase_key)

    def is_db_configured(self) -> bool:
        """Return True if a direct Postgres connection URL is set."""
        return bool(self.database_url)
