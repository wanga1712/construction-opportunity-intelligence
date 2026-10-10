"""List DIRECT-track procurements with downloaded docs (read-only)."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 25

kw = dict(require_crm_db_connect_kwargs())
crm = psycopg2.connect(**kw)
try:
    with crm.cursor() as cur:
        cur.execute(
            """
            SELECT procurement_id, count(*) AS cats,
                   bool_or(upper(coalesce(opportunity_track, '')) = 'DIRECT_SUPPLY') AS has_direct,
                   min(medal) FILTER (WHERE upper(coalesce(opportunity_track,'')) = 'DIRECT_SUPPLY') AS best_medal
            FROM crm_procurement_category_opportunities
            GROUP BY procurement_id
            HAVING bool_or(upper(coalesce(opportunity_track, '')) = 'DIRECT_SUPPLY')
            ORDER BY cats DESC, procurement_id DESC
            LIMIT %s
            """,
            (LIMIT,),
        )
        rows = cur.fetchall()

    di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
    try:
        with di.cursor() as cur:
            for pid, cats, _has, medal in rows:
                cur.execute(
                    """SELECT count(*), count(*) FILTER (WHERE download_status = 'COMPLETED')
                       FROM document_files WHERE procurement_id = %s""",
                    (pid,),
                )
                total, done = cur.fetchone()
                print("pid=%-8s cats=%-3s medal=%-8s docs=%s/%s" % (pid, cats, medal, done, total))
    finally:
        di.close()

    with crm.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM (
                SELECT procurement_id FROM crm_procurement_category_opportunities
                GROUP BY procurement_id
                HAVING bool_or(upper(coalesce(opportunity_track,'')) = 'DIRECT_SUPPLY')
            ) t
            """
        )
        print("total_direct_procurements=%s" % cur.fetchone()[0])
finally:
    crm.close()
