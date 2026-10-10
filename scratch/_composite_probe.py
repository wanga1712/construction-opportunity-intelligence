"""Почему пусто в карточке 456559 и есть ли документы у закупок категории «композиты»."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

PID = 456559
CATEGORY = "composite_structures"
KW = dict(require_crm_db_connect_kwargs())


def di_conn():
    return psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in KW.items() if k != "dbname"})


crm = psycopg2.connect(**KW)
try:
    cur = crm.cursor()
    cur.execute("select id, contract_number, auction_name, initial_price, crm_stage, source_table from crm_procurements where id=%s", (PID,))
    print("--- закупка ---")
    print("   ", cur.fetchone())
    cur.execute("select id, commercial_category_code, opportunity_track, status, commercial_state, candidate_medal, current_effective_medal, commercial_priority_score, source_sync_status from crm_procurement_category_opportunities where procurement_id=%s", (PID,))
    print("--- возможности ---")
    for row in cur.fetchall():
        print("   ", row)
    cur.execute("select procurement_scope_type, admission_state, admission_reason from crm_procurement_scope_authority where procurement_id=%s", (PID,))
    print("--- scope ---", cur.fetchone())
    cur.execute("select count(distinct procurement_id) from crm_procurement_category_opportunities where commercial_category_code=%s", (CATEGORY,))
    print("закупок с категорией %s (CRM): %s" % (CATEGORY, cur.fetchone()[0]))
    cur.execute("select distinct procurement_id from crm_procurement_category_opportunities where commercial_category_code=%s order by 1 desc limit 12", (CATEGORY,))
    cat_pids = [r[0] for r in cur.fetchall()]
    print("   примеры pid:", cat_pids)
finally:
    crm.close()

di = di_conn()
try:
    cur = di.cursor()
    cur.execute("select status, id, started_at, left(coalesce(last_error,''),60) from document_processing_queue where procurement_id=%s", (PID,))
    print("--- очередь по закупке ---")
    for row in cur.fetchall():
        print("   ", row)
    cur.execute("select id, file_name, download_status, downloaded_at from document_files where procurement_id=%s", (PID,))
    rows = cur.fetchall()
    print("--- файлы по закупке: %d ---" % len(rows))
    for row in rows[:5]:
        print("   ", row)
    cur.execute("select count(*) from document_match_details where procurement_id=%s", (PID,))
    print("--- находки ---", cur.fetchone()[0])
    for pid in cat_pids:
        cur.execute("select count(*) filter (where download_status='COMPLETED'), count(*), max(downloaded_at) from document_files where procurement_id=%s", (pid,))
        done, total, last = cur.fetchone()
        cur.execute("select count(*) from document_match_details where procurement_id=%s", (pid,))
        finds = cur.fetchone()[0]
        print("   pid=%-8s файлов %s/%s (последний %s) находок=%s" % (pid, done, total, last, finds))
finally:
    di.close()
