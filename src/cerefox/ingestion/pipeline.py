"""Ingestion pipeline: markdown text → chunks → embeddings → Supabase.

Usage::

    from cerefox.ingestion.pipeline import IngestionPipeline
    from cerefox.config import Settings
    from cerefox.db.client import CerefoxClient
    from cerefox.embeddings.mpnet import MpnetEmbedder

    settings = Settings()
    client = CerefoxClient(settings)
    embedder = MpnetEmbedder()
    pipeline = IngestionPipeline(client, embedder, settings)

    result = pipeline.ingest_text(
        text="# My note\\n\\nSome content.",
        title="My note",
        source="paste",
        project_name="personal",
    )
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cerefox.chunking.markdown import chunk_markdown

if TYPE_CHECKING:
    from cerefox.config import Settings
    from cerefox.db.client import CerefoxClient
    from cerefox.embeddings.base import Embedder

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Summary returned by every ingest_* call."""

    document_id: str
    title: str
    chunk_count: int
    total_chars: int
    skipped: bool       # True when the document was already present (hash match)
    project_id: str | None = None


class IngestionPipeline:
    """Orchestrates the full parse → chunk → embed → store flow.

    All public methods are synchronous.  For fire-and-forget background
    ingestion wrap them in a thread or process pool.

    Args:
        client: Supabase client wrapper.
        embedder: Any object satisfying the :class:`~cerefox.embeddings.base.Embedder` protocol.
        settings: Application settings (chunk sizes, etc.).
    """

    def __init__(
        self,
        client: "CerefoxClient",
        embedder: "Embedder",
        settings: "Settings",
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._settings = settings

    # ── Public API ────────────────────────────────────────────────────────

    def ingest_text(
        self,
        text: str,
        title: str,
        source: str = "paste",
        source_path: str | None = None,
        project_name: str | None = None,
        metadata: dict | None = None,
    ) -> IngestResult:
        """Ingest a raw markdown string.

        Args:
            text: Markdown content to ingest.
            title: Human-readable document title.
            source: Origin label (e.g. ``"file"``, ``"paste"``, ``"agent"``).
            source_path: Optional filesystem path or URL the content came from.
            project_name: If given, the document is linked to this project
                (created automatically if it doesn't exist).
            metadata: Arbitrary key/value pairs stored as JSONB on the document.

        Returns:
            :class:`IngestResult` summary.
        """
        content_hash = _hash(text)

        # ── Deduplication ──────────────────────────────────────────────────
        existing = self._client.get_document_by_hash(content_hash)
        if existing is not None:
            log.info("Document already ingested (hash match): %s", existing["id"])
            return IngestResult(
                document_id=existing["id"],
                title=existing.get("title", title),
                chunk_count=existing.get("chunk_count", 0),
                total_chars=existing.get("total_chars", 0),
                skipped=True,
                project_id=existing.get("project_id"),
            )

        # ── Project lookup / creation ──────────────────────────────────────
        project_id: str | None = None
        if project_name:
            project = self._client.get_or_create_project(project_name)
            project_id = project["id"]

        # ── Chunk ─────────────────────────────────────────────────────────
        s = self._settings
        chunks = chunk_markdown(
            text,
            max_chunk_chars=s.max_chunk_chars,
            min_chunk_chars=s.min_chunk_chars,
            overlap_chars=s.overlap_chars,
        )
        total_chars = sum(c.char_count for c in chunks)

        # ── Create document record ─────────────────────────────────────────
        doc_row = self._client.insert_document(
            {
                "title": title,
                "source": source,
                "source_path": source_path,
                "content_hash": content_hash,
                "project_id": project_id,
                "metadata": metadata or {},
                "chunk_count": len(chunks),
                "total_chars": total_chars,
            }
        )
        document_id: str = doc_row["id"]
        log.info("Created document %s (%d chunks)", document_id, len(chunks))

        # ── Embed + store chunks ───────────────────────────────────────────
        if chunks:
            texts = [c.content for c in chunks]
            embeddings = self._embedder.embed_batch(texts)

            chunk_rows = [
                {
                    "document_id": document_id,
                    "chunk_index": c.chunk_index,
                    "heading_path": c.heading_path,
                    "heading_level": c.heading_level,
                    "title": c.title,
                    "content": c.content,
                    "char_count": c.char_count,
                    "embedding_primary": embeddings[i],
                    "embedder_primary": self._embedder.model_name,
                }
                for i, c in enumerate(chunks)
            ]
            self._client.insert_chunks(chunk_rows)
            log.info("Stored %d chunks for document %s", len(chunks), document_id)

        return IngestResult(
            document_id=document_id,
            title=title,
            chunk_count=len(chunks),
            total_chars=total_chars,
            skipped=False,
            project_id=project_id,
        )

    def ingest_file(
        self,
        path: str,
        title: str | None = None,
        project_name: str | None = None,
        metadata: dict | None = None,
    ) -> IngestResult:
        """Read a markdown file from disk and ingest it.

        Args:
            path: Absolute or relative path to a ``.md`` file.
            title: Document title.  Defaults to the filename stem.
            project_name: Optional project to assign the document to.
            metadata: Arbitrary JSONB metadata.

        Returns:
            :class:`IngestResult` summary.
        """
        from pathlib import Path  # noqa: PLC0415

        p = Path(path)
        text = p.read_text(encoding="utf-8")
        return self.ingest_text(
            text=text,
            title=title or p.stem,
            source="file",
            source_path=str(p.resolve()),
            project_name=project_name,
            metadata=metadata,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _hash(text: str) -> str:
    """Return a SHA-256 hex digest of the UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
