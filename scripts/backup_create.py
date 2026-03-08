#!/usr/bin/env python3
"""Create a local JSON snapshot backup of the Cerefox knowledge base.

Usage:
    python scripts/backup_create.py
    python scripts/backup_create.py --label before-migration
    python scripts/backup_create.py --dir /path/to/backups
    python scripts/backup_create.py --git-commit   # auto-commit to git

Requires CEREFOX_SUPABASE_URL and CEREFOX_SUPABASE_KEY in your .env file.
The backup is written to CEREFOX_BACKUP_DIR (default: ./backups).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cerefox.backup.fs_backup import FileSystemBackup
from cerefox.config import Settings
from cerefox.db.client import CerefoxClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Cerefox knowledge base backup.")
    parser.add_argument("--label", "-l", default=None, help="Optional label added to the filename.")
    parser.add_argument(
        "--dir",
        "-d",
        default=None,
        help="Backup directory (overrides CEREFOX_BACKUP_DIR from .env).",
    )
    parser.add_argument(
        "--git-commit",
        action="store_true",
        default=False,
        help="Commit the backup file to the git repository in the backup directory.",
    )
    args = parser.parse_args()

    settings = Settings()

    if not settings.is_supabase_configured():
        print("❌  CEREFOX_SUPABASE_URL and CEREFOX_SUPABASE_KEY must be set.")
        sys.exit(1)

    backup_dir = args.dir or settings.backup_dir
    client = CerefoxClient(settings)
    backup = FileSystemBackup(client, backup_dir=backup_dir)

    print(f"Creating backup in {backup_dir} …")
    try:
        info = backup.create(label=args.label, git_commit=args.git_commit)
    except Exception as exc:
        print(f"❌  Backup failed: {exc}")
        sys.exit(1)

    print(f"✓  Backup complete")
    print(f"   Path       : {info.path}")
    print(f"   Documents  : {info.document_count}")
    print(f"   Chunks     : {info.chunk_count}")
    print(f"   Size       : {info.size_bytes:,} bytes")
    if args.git_commit:
        print("   Git commit : attempted (check logs for result)")


if __name__ == "__main__":
    main()
