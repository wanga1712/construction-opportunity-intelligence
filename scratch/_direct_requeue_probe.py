"""Read-only: состояние очереди по DIRECT-закупкам (кому нужно перекачать документы)."""
import json
import os
import sys
from collections import Counter

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

rows = [json.loads(l) for l in open("/tmp/direct_batch.jsonl", encoding="utf-8") if l.strip()]
no_data = {r["pid"] for r in rows if not (r.get("spec") or r.get("tech") or r.get("sections"))}

di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with di.cursor() as cur:
        cur.execute(
            """SELECT procurement_id, status, pipeline_generation, queue_lane, source_table
               FROM document_processing_queue WHERE procurement_id = ANY(%s)""",
            (pids,),
        )
        queue = cur.fetchall()
    with di.cursor() as cur:
        cur.execute(
            """SELECT procurement_id, count(*),
                      count(*) FILTER (WHERE local_deleted_at IS NOT NULL)
               FROM document_files WHERE procurement_id = ANY(%s)
               GROUP BY 1""",
            (pids,),
        )
        files = cur.fetchall()
finally:
    di.close()

q_by_pid = {}
for pid, status, gen, lane, table in queue:
    q_by_pid.setdefault(pid, []).append((status, gen, lane, table))

print("direct_pids=%d queue_rows=%d pids_in_queue=%d" % (len(pids), len(queue), len(q_by_pid)))
print("--- статусы очереди (по строкам) ---")
for status, count in Counter(r[1] for r in queue).most_common():
    print("%6d  %s" % (count, status))
print("--- поколения пайплайна ---")
for gen, count in Counter(r[2] for r in queue).most_common():
    print("%6d  %s" % (count, gen))
print("--- lanes ---")
for lane, count in Counter(r[3] for r in queue).most_common(8):
    print("%6d  %s" % (count, lane))

targets = sorted(no_data)
in_queue = [p for p in targets if p in q_by_pid]
print("--- целевые (без данных) ---")
print("pids_without_data=%d, из них в очереди=%d, без очереди=%d" % (
    len(targets), len(in_queue), len(targets) - len(in_queue)))
for status, count in Counter(s for p in in_queue for s, _, _, _ in q_by_pid[p]).most_common():
    print("%6d  %s (строк)" % (count, status))
print("--- файлы по целевым ---")
files_by_pid = {pid: (total, purged) for pid, total, purged in files}
missing_files = sum(t for p, t, _ in files if p in no_data)
purged_files = sum(pg for p, _, pg in files if p in no_data)
print("files_total=%d purged=%d" % (missing_files, purged_files))
