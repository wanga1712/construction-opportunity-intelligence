#!/usr/bin/env python3
"""Keep downloaded archive/heavy artifacts durable and rebind local_path.

Invariant: 1 selected archive -> 1 HTTP artifact -> N children parsed -> facts
-> archive artifact kept under /data/tender-documents/durable (outside the
retention root) -> later reprocess = HTTP 0.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

LANE = os.getenv("DURABLE_LANE", "queue_v2_heavy")
DOWNLOAD_ROOT = Path(os.getenv("DOCUMENT_DOWNLOAD_DIR", "/data/tender-documents/downloads"))
DURABLE_ROOT = Path(os.getenv("DOCUMENT_DURABLE_DIR", "/data/tender-documents/durable"))
_ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z", ".001", ".002", ".003", ".004", ".007")


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def main() -> int:
    di = psycopg2.connect(**di_dsn())
    try:
        rows = query(
            di,
            "SELECT id, procurement_id, selected_documents FROM document_processing_queue"
            " WHERE queue_lane=%s AND status IN ('COMPLETED','FAILED')",
            (LANE,),
        )
        c = Counter()
        for row in rows:
            task_dir = DOWNLOAD_ROOT / str(int(row["id"]))
            for entry in row.get("selected_documents") or []:
                fname = str(entry.get("file_name") or "")
                if not fname.lower().endswith(_ARCHIVE_SUFFIXES):
                    c["NOT_ARCHIVE"] += 1
                    continue
                doc_id = entry.get("source_document_id")
                src = None
                if task_dir.exists():
                    for p in task_dir.rglob("*"):
                        if p.is_file() and p.name == fname:
                            src = p
                            break
                if src is None:
                    c["SOURCE_MISSING"] += 1
                    continue
                dest_dir = DURABLE_ROOT / str(int(row["procurement_id"]))
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / fname
                if not dest.exists():
                    shutil.copy2(src, dest)
                    c["COPIED"] += 1
                else:
                    c["ALREADY_DURABLE"] += 1
                if doc_id is not None:
                    with di.cursor() as cur:
                        cur.execute(
                            "UPDATE document_files SET local_path=%s, local_deleted_at=NULL,"
                            " download_status='COMPLETED' WHERE id=%s",
                            (str(dest), int(doc_id)),
                        )
                    c["REBOUND"] += 1
        di.commit()
        print(f"DURABLE_ROOT={DURABLE_ROOT}")
        for k, v in sorted(c.items()):
            print(f"{k}={v}")
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
