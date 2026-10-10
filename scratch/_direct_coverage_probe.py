"""Coverage probe: DIRECT procurements with docs, split by file formats."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

kw = dict(require_crm_db_connect_kwargs())
crm = psycopg2.connect(**kw)
try:
    with crm.cursor() as cur:
        cur.execute(
            """SELECT procurement_id FROM crm_procurement_category_opportunities
               WHERE upper(coalesce(opportunity_track,''))='DIRECT_SUPPLY'
               GROUP BY procurement_id"""
        )
        pids = [r[0] for r in cur.fetchall()]
finally:
    crm.close()

di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with di.cursor() as cur:
        cur.execute(
            """
            SELECT lower(coalesce(substring(local_path from '\\.([A-Za-z0-9]+)$'), '?')),
                   count(*) AS files, count(DISTINCT procurement_id) AS pids
            FROM document_files
            WHERE download_status = 'COMPLETED' AND local_path IS NOT NULL
              AND procurement_id = ANY(%s)
            GROUP BY 1 ORDER BY 2 DESC
            """,
            (pids,),
        )
        print("direct_pids=%d" % len(pids))
        for ext, files, npids in cur.fetchall():
            print("%-6s files=%-7s pids=%s" % (ext, files, npids))
        cur.execute(
            """
            SELECT count(DISTINCT procurement_id) FROM document_files
            WHERE download_status='COMPLETED' AND local_path IS NOT NULL
              AND procurement_id = ANY(%s) AND lower(local_path) LIKE '%%.docx'
            """,
            (pids,),
        )
        print("pids_with_docx=%s" % cur.fetchone()[0])
        cur.execute(
            """
            SELECT count(DISTINCT procurement_id) FROM document_files
            WHERE download_status='COMPLETED' AND local_path IS NOT NULL
              AND procurement_id = ANY(%s)
            """,
            (pids,),
        )
        print("pids_with_docs=%s" % cur.fetchone()[0])
finally:
    di.close()
