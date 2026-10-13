#!/usr/bin/env python3
"""Idempotent duplicate sweeper for document_files.

Neutralizes duplicate rows for the same physical document of the same procurement
(`(procurement_id, physical_download_key)`), keeping one survivor:
a row with `local_path` first, else the smallest `id`.

Nothing is deleted: the rest get download_status='SKIPPED' and
error_message='duplicate_of:<survivor_id>' (reversible).

Default is dry-run; --apply writes. Safe to run repeatedly / on a timer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2

SWEEP_SQL = """
WITH ranked AS (
  SELECT id,
         row_number() OVER (
           PARTITION BY procurement_id, physical_download_key
           ORDER BY (local_path IS NOT NULL) DESC, id ASC) AS rn,
         first_value(id) OVER (
           PARTITION BY procurement_id, physical_download_key
           ORDER BY (local_path IS NOT NULL) DESC, id ASC) AS survivor
    FROM document_files
   WHERE coalesce(physical_download_key, '') <> ''
     AND download_status <> 'SKIPPED'
)
UPDATE document_files f
   SET download_status = 'SKIPPED',
       error_message = 'duplicate_of:' || r.survivor
  FROM ranked r
 WHERE f.id = r.id AND r.rn > 1
"""


def di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


ACTIVE_DUP_SQL = """
SELECT count(*) FROM (
  SELECT procurement_id, physical_download_key
    FROM document_files
   WHERE coalesce(physical_download_key, '') <> ''
     AND download_status IN ('PENDING', 'COMPLETED')
   GROUP BY 1, 2 HAVING count(*) > 1) t
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    di = di_conn()
    try:
        cur = di.cursor()
        cur.execute(ACTIVE_DUP_SQL)
        before = int(cur.fetchone()[0] or 0)
        neutralized = 0
        if args.apply:
            cur.execute(SWEEP_SQL)
            neutralized = cur.rowcount or 0
            di.commit()
        cur.execute(ACTIVE_DUP_SQL)
        after = int(cur.fetchone()[0] or 0)
        print(json.dumps({
            "apply": bool(args.apply),
            "active_duplicate_groups_before": before,
            "neutralized_now": neutralized,
            "active_duplicate_groups_after": after,
        }, ensure_ascii=False))
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
