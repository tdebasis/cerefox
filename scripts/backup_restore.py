#!/usr/bin/env python3
"""Restore a Cerefox knowledge base from a JSON snapshot backup.

Usage:
    python scripts/backup_restore.py backups/cerefox-20260307T120000Z.json
    python scripts/backup_restore.py backup.json --dry-run

Existing documents (matched by content hash) are skipped — the restore is
idempotent and safe to run against a non-empty database.

Requires CEREFOX_SUPABASE_URL and CEREFOX_SUPABASE_KEY in your .env file.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cerefox.backup.fs_backup import FileSystemBackup
from cerefox.config import Settings
from cerefox.db.client import CerefoxClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a Cerefox backup.")
    parser.add_argument("backup_file", help="Path to the backup JSON file.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the backup without writing to the database.",
    )
    args = parser.parse_args()

    settings = Settings()

    if not settings.is_supabase_configured():
        print("❌  CEREFOX_SUPABASE_URL and CEREFOX_SUPABASE_KEY must be set.")
        sys.exit(1)

    client = CerefoxClient(settings)
    backup = FileSystemBackup(client, backup_dir=str(Path(args.backup_file).parent))

    mode = "DRY RUN — no writes" if args.dry_run else "LIVE"
    print(f"Restoring from {args.backup_file} [{mode}] …")

    try:
        stats = backup.restore(args.backup_file, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌  {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"❌  Restore failed: {exc}")
        sys.exit(1)

    print(f"{'✓' if not args.dry_run else 'ℹ'}  Restore complete")
    print(f"   Restored : {stats['restored']}")
    print(f"   Skipped  : {stats['skipped']} (already present)")
    print(f"   Errors   : {stats['errors']}")

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
