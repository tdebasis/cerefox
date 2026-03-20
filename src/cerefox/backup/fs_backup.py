"""File system backup and restore for Cerefox documents.

Each backup is a single JSON file containing a full snapshot of all documents
and their chunks.  The file is written atomically (temp-file + rename) to
avoid half-written backups.

Backup file format::

    {
        "version": 1,
        "created_at": "2026-03-07T12:00:00Z",
        "document_count": 42,
        "chunk_count": 317,
        "documents": [
            {
                "id": "...",
                "title": "...",
                ...document columns...,
                "chunks": [
                    {"chunk_index": 0, "content": "...", ...},
                    ...
                ]
            },
            ...
        ]
    }

Usage::

    from cerefox.backup.fs_backup import FileSystemBackup
    backup = FileSystemBackup(client, backup_dir="./backups")
    info = backup.create()
    print(info.path)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cerefox.db.client import CerefoxClient

log = logging.getLogger(__name__)

_BACKUP_VERSION = 1


@dataclass
class BackupInfo:
    """Metadata about a completed backup operation."""

    path: str
    document_count: int
    chunk_count: int
    size_bytes: int
    created_at: str


class FileSystemBackup:
    """Creates and restores JSON snapshot backups on the local file system.

    Args:
        client: Supabase client wrapper used to fetch / restore data.
        backup_dir: Directory where backup files are stored.  Created
            automatically if it doesn't exist.
    """

    def __init__(self, client: "CerefoxClient", backup_dir: str = "./backups") -> None:
        self._client = client
        self._backup_dir = Path(backup_dir)

    # ── Create ────────────────────────────────────────────────────────────

    def create(
        self, label: str | None = None, *, git_commit: bool = False
    ) -> BackupInfo:
        """Dump all documents and chunks to a timestamped JSON file.

        Args:
            label: Optional suffix added to the filename (e.g. ``"before-migration"``).
            git_commit: If ``True`` and the backup directory is inside a git repo,
                commit the backup file automatically.

        Returns:
            :class:`BackupInfo` with the path and statistics.
        """
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(tz=timezone.utc)
        ts_str = ts.strftime("%Y%m%dT%H%M%SZ")
        filename = f"cerefox-{ts_str}{('-' + label) if label else ''}.json"
        dest = self._backup_dir / filename

        documents = self._client.list_all_documents()
        doc_count = len(documents)
        chunk_count = 0

        enriched: list[dict] = []
        for doc in documents:
            doc_id = doc["id"]
            chunks = self._client.list_chunks_for_document(doc_id)
            chunk_count += len(chunks)
            enriched.append({**doc, "chunks": chunks})

        payload = {
            "version": _BACKUP_VERSION,
            "created_at": ts.isoformat(),
            "document_count": doc_count,
            "chunk_count": chunk_count,
            "documents": enriched,
        }

        _atomic_write(dest, payload)
        size = dest.stat().st_size
        log.info("Backup written to %s (%d docs, %d chunks, %d bytes)", dest, doc_count, chunk_count, size)

        if git_commit:
            _git_commit_backup(dest, label)

        return BackupInfo(
            path=str(dest),
            document_count=doc_count,
            chunk_count=chunk_count,
            size_bytes=size,
            created_at=ts.isoformat(),
        )

    # ── Restore ───────────────────────────────────────────────────────────

    def restore(self, backup_path: str, *, dry_run: bool = False) -> dict:
        """Restore documents and chunks from a backup JSON file.

        Existing documents whose ``content_hash`` already exists in the
        database are skipped (idempotent).  Chunks for skipped documents
        are also skipped.

        Args:
            backup_path: Path to the backup JSON file.
            dry_run: If ``True``, parse and validate the backup but make no
                database writes.

        Returns:
            A dict with ``{"restored": int, "skipped": int, "errors": int}``.
        """
        path = Path(backup_path)
        if not path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)

        version = payload.get("version")
        if version != _BACKUP_VERSION:
            raise ValueError(f"Unsupported backup version: {version!r} (expected {_BACKUP_VERSION})")

        documents: list[dict] = payload.get("documents", [])
        stats = {"restored": 0, "skipped": 0, "errors": 0}

        for doc in documents:
            chunks: list[dict] = doc.pop("chunks", [])
            content_hash = doc.get("content_hash")

            try:
                existing = self._client.get_document_by_hash(content_hash) if content_hash else None
                if existing is not None:
                    log.debug("Skipping already-present document: %s", doc.get("id"))
                    stats["skipped"] += 1
                    continue

                if not dry_run:
                    # Strip server-generated fields before inserting.
                    insert_doc = {
                        k: v for k, v in doc.items()
                        if k not in ("id", "created_at", "updated_at")
                    }
                    new_doc = self._client.insert_document(insert_doc)
                    new_id = new_doc["id"]

                    chunk_rows = [
                        {k: v for k, v in ch.items() if k not in ("id", "created_at", "updated_at", "document_id")}
                        | {"document_id": new_id}
                        for ch in chunks
                    ]
                    if chunk_rows:
                        self._client.insert_chunks(chunk_rows)

                stats["restored"] += 1
            except Exception as exc:  # noqa: BLE001
                log.error("Error restoring document %s: %s", doc.get("id"), exc)
                stats["errors"] += 1

        log.info("Restore complete: %s", stats)
        return stats

    # ── List ──────────────────────────────────────────────────────────────

    def list_backups(self) -> list[dict]:
        """Return metadata for all backup files in the backup directory.

        Returns an empty list if the directory doesn't exist yet.
        """
        if not self._backup_dir.exists():
            return []

        result = []
        for p in sorted(self._backup_dir.glob("cerefox-*.json")):
            try:
                stat = p.stat()
                result.append(
                    {
                        "filename": p.name,
                        "path": str(p),
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                    }
                )
            except OSError:
                pass  # race condition — file disappeared
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────


def _atomic_write(dest: Path, payload: dict) -> None:
    """Write *payload* as JSON to *dest* atomically via a temp file."""
    dir_ = dest.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _git_commit_backup(backup_path: Path, label: str | None = None) -> None:
    """Stage and commit a backup file in its git repository.

    Silently skips if git is not available or the directory is not a git repo.
    """
    import subprocess  # noqa: PLC0415

    repo_dir = backup_path.parent
    commit_msg = f"backup: {backup_path.name}" + (f" ({label})" if label else "")
    try:
        subprocess.run(
            ["git", "add", str(backup_path)],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(repo_dir),
            check=True,
            capture_output=True,
        )
        log.info("Backup committed to git: %s", commit_msg)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log.warning("Git commit skipped: %s", exc)
