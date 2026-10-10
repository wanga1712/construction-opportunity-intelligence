"""Mark document_files rows whose file is already gone (local_deleted_at).

Backfill for the retention bug: files were unlinked without setting
local_deleted_at, so ~thousands of rows looked available while the disk was
empty. Read-only for disk; writes only local_deleted_at.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=True)

import psycopg2  # noqa: E402

BATCH = 5000

conn = psycopg2.connect(
    host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
    dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
    user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
    password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
)
cur = conn.cursor()
cur.execute(
    """SELECT id, local_path FROM document_files
       WHERE download_status='COMPLETED' AND local_deleted_at IS NULL"""
)
rows = cur.fetchall()
print("CHECKED", len(rows), flush=True)

missing = []
for file_id, path in rows:
    if not path or not os.path.exists(path):
        missing.append(file_id)

print("MISSING_ON_DISK", len(missing), flush=True)
for start in range(0, len(missing), BATCH):
    chunk = [(i,) for i in missing[start:start + BATCH]]
    cur.executemany(
        "UPDATE document_files SET local_deleted_at = NOW() WHERE id = %s", chunk
    )
    conn.commit()
    print("MARKED", start + len(chunk), flush=True)

cur.execute(
    """SELECT COUNT(*) FROM document_files
       WHERE download_status='COMPLETED' AND local_deleted_at IS NOT NULL"""
)
print("TOTAL_MARKED_DELETED", cur.fetchone()[0])
conn.close()
