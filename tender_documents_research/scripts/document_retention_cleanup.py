"""Document retention cleanup script for Tender Documents Pipeline on S13.

Safely removes raw downloaded tender documents older than specified retention period (default 3 days).
Extracted text and metadata are preserved in PostgreSQL (document_intelligence / crm).
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("document_retention")

DEFAULT_RETENTION_DAYS = 3
DEFAULT_TARGET_DIRS = [
    "/data/tender-documents/downloads",
    "/data/tender-documents/downloads-open",
    "/data/tender-documents/downloads-awarded",
    "/data/tender-documents/downloads-computers",
    "/data/tender-documents/downloads-computers-2",
    "/data/tender-documents/temp",
    "/data/tender-documents/ocr-tmp",
    "/data/tender-documents/parser-tmp",
]


def _open_db():
    """Document-intelligence connection for marking deleted files."""
    from dotenv import load_dotenv

    load_dotenv("/opt/CRM_Streamlit/.env", override=True)
    import psycopg2

    return psycopg2.connect(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
    )


def cleanup_directory(
    target_dir: str,
    cutoff_ts: float,
    delete: bool = False,
    on_deleted: Optional[Callable[[str], Any]] = None,
) -> Tuple[int, int, int]:
    """Clean files and empty dirs in target_dir older than cutoff_ts.
    
    Returns (files_deleted, bytes_freed, dirs_removed).
    """
    path = Path(target_dir)
    if not path.exists():
        logger.debug("Directory %s does not exist, skipping", target_dir)
        return 0, 0, 0

    files_deleted = 0
    bytes_freed = 0
    dirs_removed = 0

    # First pass: remove files older than cutoff
    for root, dirs, files in os.walk(str(path), topdown=False):
        for f in files:
            file_path = os.path.join(root, f)
            try:
                st = os.lstat(file_path)
                mtime = st.st_mtime
                if mtime < cutoff_ts:
                    size = st.st_size
                    if delete:
                        try:
                            os.unlink(file_path)
                        except OSError as e:
                            logger.warning("Failed to unlink %s: %s", file_path, e)
                            continue
                        # Accounting: a file that no longer exists must not look
                        # "present" in document_files (local_deleted_at was never
                        # set before, so 870 of 940 estimates looked available).
                        if on_deleted is not None:
                            try:
                                on_deleted(file_path)
                            except Exception as exc:  # never fail retention on DB
                                logger.warning("Mark deleted failed for %s: %s", file_path, exc)
                    files_deleted += 1
                    bytes_freed += size
            except (OSError, FileNotFoundError):
                continue

        # Second pass: remove empty directories (except target_dir itself)
        if root != str(path):
            try:
                if not os.listdir(root):
                    if delete:
                        os.rmdir(root)
                    dirs_removed += 1
            except (OSError, FileNotFoundError):
                pass

    return files_deleted, bytes_freed, dirs_removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Tender document raw retention cleanup")
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS, help=f"Retention days (default: {DEFAULT_RETENTION_DAYS})")
    parser.add_argument("--delete", action="store_true", help="Actually delete files (default: dry run)")
    parser.add_argument("--peer-psql", action="store_true", help="Flag for systemd compatibility (accepted)")
    parser.add_argument("--target-dirs", nargs="*", default=DEFAULT_TARGET_DIRS, help="Target directories to clean")
    args = parser.parse_args()

    cutoff_ts = time.time() - (args.days * 86400)
    logger.info("Starting document retention cleanup: days=%d (cutoff ts=%.0f), delete=%s", args.days, cutoff_ts, args.delete)

    total_files = 0
    total_bytes = 0
    total_dirs = 0

    marker_conn = None
    marker_cur = None
    marked = [0]
    if args.delete and args.peer_psql:
        try:
            marker_conn = _open_db()
            marker_cur = marker_conn.cursor()

            def _mark(path: str) -> None:
                marker_cur.execute(
                    """UPDATE document_files SET local_deleted_at = NOW()
                       WHERE local_path = %s AND local_deleted_at IS NULL""",
                    (path,),
                )
                marked[0] += marker_cur.rowcount or 0

            on_deleted = _mark
        except Exception as exc:
            logger.warning("Deleted-file accounting disabled: %s", exc)
            on_deleted = None
    else:
        on_deleted = None

    for d in args.target_dirs:
        logger.info("Scanning target directory: %s", d)
        f_count, b_count, d_count = cleanup_directory(
            d, cutoff_ts, delete=args.delete, on_deleted=on_deleted
        )
        mb_freed = b_count / (1024 * 1024)
        logger.info("  -> %s: %d files (%.2f MB), %d empty dirs", d, f_count, mb_freed, d_count)
        total_files += f_count
        total_bytes += b_count
        total_dirs += d_count

    if marker_conn is not None:
        try:
            marker_conn.commit()
        finally:
            marker_conn.close()
        logger.info("Marked rows: local_deleted_at=%d", marked[0])

    total_gb = total_bytes / (1024 * 1024 * 1024)
    mode_str = "DELETED" if args.delete else "DRY-RUN (would delete)"
    logger.info("Cleanup finished [%s]: %d files, %.2f GB freed, %d dirs removed", mode_str, total_files, total_gb, total_dirs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
