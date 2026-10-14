#!/usr/bin/env python3
"""Reversibly restore document_files rows wrongly neutralized by the coarse dedup identity.

Before ARCHIVE_MEMBER_DEDUP_IDENTITY_V1 the sweeper partitioned duplicates by
`(procurement_id, physical_download_key)` only. Archive members extracted from the
same archive inherit the parent's `physical_download_key`, so they were marked
`download_status='SKIPPED'`, `error_message='duplicate_of:<survivor>'` even though
they are distinct physical files (their `url_hash` differs from the survivor's).

Candidate rows = SKIPPED rows whose `error_message` is `duplicate_of:<id>` and whose
`(url_hash, file_name)` differs from the survivor's `(url_hash, file_name)`.

Restore = set `download_status='PENDING'` and keep the previous marker:

    error_message = 'restored_from:archive_member_dedup_identity_v1; prev=duplicate_of:<n>'

Nothing is deleted and the change is reversible. Default is dry-run; --apply writes.
`--pattern` filters by file name (default `%.gsfx`).
"""
from __future__ import annotations

import argparse
import json
import os

import psycopg2

CANDIDATE_CTE = r"""
cand AS (
  SELECT f.id, f.procurement_id
    FROM document_files f
    JOIN document_files s
      ON s.id = substring(f.error_message from 'duplicate_of:(\d+)')::bigint
   WHERE f.download_status = 'SKIPPED'
     AND f.error_message LIKE 'duplicate_of:%%'
     AND f.file_name LIKE %s
     AND coalesce(f.url_hash, f.file_name, '')
         IS DISTINCT FROM coalesce(s.url_hash, s.file_name, '')
)
"""

COUNT_SQL = f"WITH {CANDIDATE_CTE} SELECT count(*), count(DISTINCT procurement_id) FROM cand"

RESTORE_SQL = f"""
WITH {CANDIDATE_CTE}
UPDATE document_files f
   SET download_status = 'PENDING',
       error_message = 'restored_from:archive_member_dedup_identity_v1; prev=' || f.error_message
  FROM cand
 WHERE f.id = cand.id
   AND f.download_status = 'SKIPPED'
"""


def di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pattern", default="%.gsfx")
    args = ap.parse_args()

    di = di_conn()
    try:
        cur = di.cursor()
        cur.execute(COUNT_SQL, (args.pattern,))
        before_rows, before_procs = cur.fetchone()
        restored = 0
        if args.apply:
            cur.execute(RESTORE_SQL, (args.pattern,))
            restored = cur.rowcount or 0
            di.commit()
        cur.execute(COUNT_SQL, (args.pattern,))
        after_rows, after_procs = cur.fetchone()
        print(json.dumps({
            "apply": bool(args.apply),
            "pattern": args.pattern,
            "candidates_before": int(before_rows or 0),
            "candidates_procurements_before": int(before_procs or 0),
            "restored_now": int(restored),
            "candidates_after": int(after_rows or 0),
            "candidates_procurements_after": int(after_procs or 0),
        }, ensure_ascii=False))
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
