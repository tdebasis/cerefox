"""Supabase client wrapper for Cerefox.

Thin wrapper around supabase-py that provides a clean, typed interface
for the operations Cerefox needs. All search and retrieval goes through
the RPCs defined in rpcs.sql.
"""

from __future__ import annotations

import logging
from typing import Any

from supabase import Client, create_client

from cerefox.config import Settings

logger = logging.getLogger(__name__)


class CerefoxClient:
    """Lightweight wrapper around the Supabase Python client.

    Provides typed methods for calling Cerefox RPCs and performing
    basic table operations. Does not handle embedding or chunking —
    those live in their respective modules.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client | None = None

    @property
    def client(self) -> Client:
        """Lazily initialize and return the Supabase client."""
        if self._client is None:
            if not self._settings.is_supabase_configured():
                raise RuntimeError(
                    "Supabase is not configured. "
                    "Set CEREFOX_SUPABASE_URL and CEREFOX_SUPABASE_KEY."
                )
            self._client = create_client(
                self._settings.supabase_url,
                self._settings.supabase_key,
            )
        return self._client

    def rpc(self, function_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Call a Supabase RPC and return the result rows.

        Args:
            function_name: Name of the Postgres function (e.g. 'cerefox_hybrid_search').
            params: Parameters to pass to the function.

        Returns:
            List of result rows as dicts.

        Raises:
            RuntimeError: If the RPC call fails.
        """
        try:
            response = self.client.rpc(function_name, params).execute()
            return response.data or []
        except Exception as exc:
            logger.error("RPC %s failed: %s", function_name, exc)
            raise RuntimeError(f"RPC {function_name!r} failed: {exc}") from exc

    # ── Documents ──────────────────────────────────────────────────────────────

    def insert_document(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a document record and return the created row."""
        try:
            response = self.client.table("cerefox_documents").insert(data).execute()
            if not response.data:
                raise RuntimeError("Insert returned no data")
            return response.data[0]
        except Exception as exc:
            logger.error("insert_document failed: %s", exc)
            raise RuntimeError(f"insert_document failed: {exc}") from exc

    def get_document_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        """Return the document with the given content hash, or None if not found."""
        try:
            response = (
                self.client.table("cerefox_documents")
                .select("*")
                .eq("content_hash", content_hash)
                .limit(1)
                .execute()
            )
            return response.data[0] if response.data else None
        except Exception as exc:
            logger.error("get_document_by_hash failed: %s", exc)
            raise RuntimeError(f"get_document_by_hash failed: {exc}") from exc

    def update_document_chunk_stats(
        self, document_id: str, chunk_count: int, total_chars: int
    ) -> None:
        """Update chunk_count and total_chars on a document after ingestion."""
        try:
            self.client.table("cerefox_documents").update(
                {"chunk_count": chunk_count, "total_chars": total_chars}
            ).eq("id", document_id).execute()
        except Exception as exc:
            logger.error("update_document_chunk_stats failed: %s", exc)
            raise RuntimeError(f"update_document_chunk_stats failed: {exc}") from exc

    def delete_document(self, document_id: str) -> None:
        """Delete a document and cascade-delete its chunks."""
        try:
            self.client.table("cerefox_documents").delete().eq("id", document_id).execute()
        except Exception as exc:
            logger.error("delete_document failed: %s", exc)
            raise RuntimeError(f"delete_document failed: {exc}") from exc

    def list_documents(
        self,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List documents, optionally filtered by project."""
        try:
            query = (
                self.client.table("cerefox_documents")
                .select("id, title, source, source_path, project_id, metadata, chunk_count, total_chars, created_at")
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
            )
            if project_id:
                query = query.eq("project_id", project_id)
            return query.execute().data or []
        except Exception as exc:
            logger.error("list_documents failed: %s", exc)
            raise RuntimeError(f"list_documents failed: {exc}") from exc

    # ── Chunks ─────────────────────────────────────────────────────────────────

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert multiple chunk records and return the created rows."""
        if not chunks:
            return []
        try:
            response = self.client.table("cerefox_chunks").insert(chunks).execute()
            return response.data or []
        except Exception as exc:
            logger.error("insert_chunks failed: %s", exc)
            raise RuntimeError(f"insert_chunks failed: {exc}") from exc

    # ── Projects ───────────────────────────────────────────────────────────────

    def get_or_create_project(self, name: str, description: str = "") -> dict[str, Any]:
        """Return an existing project by name, or create it if it doesn't exist."""
        try:
            response = (
                self.client.table("cerefox_projects")
                .select("*")
                .eq("name", name)
                .limit(1)
                .execute()
            )
            if response.data:
                return response.data[0]
            # Create it
            create_resp = (
                self.client.table("cerefox_projects")
                .insert({"name": name, "description": description})
                .execute()
            )
            if not create_resp.data:
                raise RuntimeError("Project creation returned no data")
            return create_resp.data[0]
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error("get_or_create_project failed: %s", exc)
            raise RuntimeError(f"get_or_create_project failed: {exc}") from exc

    def list_projects(self) -> list[dict[str, Any]]:
        """Return all projects ordered by name."""
        try:
            response = (
                self.client.table("cerefox_projects")
                .select("*")
                .order("name")
                .execute()
            )
            return response.data or []
        except Exception as exc:
            logger.error("list_projects failed: %s", exc)
            raise RuntimeError(f"list_projects failed: {exc}") from exc

    # ── Search (convenience wrappers around RPCs) ──────────────────────────────

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        match_count: int = 10,
        alpha: float = 0.7,
        use_upgrade: bool = False,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid FTS + semantic search."""
        return self.rpc(
            "cerefox_hybrid_search",
            {
                "p_query_text": query_text,
                "p_query_embedding": query_embedding,
                "p_match_count": match_count,
                "p_alpha": alpha,
                "p_use_upgrade": use_upgrade,
                "p_project_id": project_id,
            },
        )

    def fts_search(
        self,
        query_text: str,
        match_count: int = 10,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text keyword search."""
        return self.rpc(
            "cerefox_fts_search",
            {
                "p_query_text": query_text,
                "p_match_count": match_count,
                "p_project_id": project_id,
            },
        )

    def semantic_search(
        self,
        query_embedding: list[float],
        match_count: int = 10,
        use_upgrade: bool = False,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Pure vector similarity search."""
        return self.rpc(
            "cerefox_semantic_search",
            {
                "p_query_embedding": query_embedding,
                "p_match_count": match_count,
                "p_use_upgrade": use_upgrade,
                "p_project_id": project_id,
            },
        )

    def reconstruct_doc(self, document_id: str) -> dict[str, Any] | None:
        """Reconstruct the full markdown content of a document from its chunks."""
        rows = self.rpc("cerefox_reconstruct_doc", {"p_document_id": document_id})
        return rows[0] if rows else None
