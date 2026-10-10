"""Extraction coverage probe: file types vs extracted content per DIRECT procurement."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

kw = dict(require_crm_db_connect_kwargs())
di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with di.cursor() as cur:
        cur.execute(
            """
            SELECT lower(coalesce(nullif(regexp_replace(local_path, '^.*\\.', ''), local_path), '?')),
                   count(*)
            FROM document_files
            WHERE download_status = 'COMPLETED' AND local_path IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC LIMIT 15
            """
        )
        print("--- extensions (all completed docs) ---")
        for ext, n in cur.fetchall():
            print("%-10s %s" % (ext, n))
    for pid in (461288, 461281, 461274, 461299):
        with di.cursor() as cur:
            cur.execute(
                """SELECT local_path, download_status FROM document_files
                   WHERE procurement_id = %s ORDER BY id""",
                (pid,),
            )
            rows = cur.fetchall()
        print("--- pid %s (%d files) ---" % (pid, len(rows)))
        for path, status in rows:
            name = os.path.basename(path or "")
            print("   %-12s %s" % (status, name.encode("ascii", "replace").decode()))
finally:
    di.close()
