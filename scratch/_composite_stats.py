"""Сколько закупок категории composite_structures реально имеют документы и находки."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

CATEGORY = os.getenv("CATEGORY", "composite_structures")
KW = dict(require_crm_db_connect_kwargs())

crm = psycopg2.connect(**KW)
try:
    with crm.cursor() as cur:
        cur.execute(
            """select distinct procurement_id, opportunity_track
               from crm_procurement_category_opportunities
               where commercial_category_code=%s""", (CATEGORY,))
        rows = cur.fetchall()
finally:
    crm.close()
pids = [r[0] for r in rows]
tracks = {}
for pid, track in rows:
    tracks[track] = tracks.get(track, 0) + 1
print("категория %s: закупок=%d, треки=%s" % (CATEGORY, len(pids), tracks))

di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in KW.items() if k != "dbname"})
try:
    with di.cursor() as cur:
        cur.execute(
            """select procurement_id, count(*), count(*) filter (where local_deleted_at is null)
               from document_files where download_status='COMPLETED' and procurement_id = ANY(%s)
               group by 1""", (pids,))
        files = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute(
            """select procurement_id, count(*) from document_match_details
               where procurement_id = ANY(%s) group by 1""", (pids,))
        finds = dict(cur.fetchall())
        cur.execute("select count(*) from document_processing_queue where procurement_id = ANY(%s)", (pids,))
        in_queue = cur.fetchone()[0]
finally:
    di.close()

with_files = [p for p in pids if files.get(p, (0, 0))[0] > 0]
files_on_disk = [p for p in pids if files.get(p, (0, 0))[1] > 0]
with_finds = [p for p in pids if finds.get(p, 0) > 0]
print("с когда-либо скачанными файлами: %d" % len(with_files))
print("файлы ещё на диске:              %d" % len(files_on_disk))
print("с находками:                     %d" % len(with_finds))
print("строк в документной очереди:     %d" % in_queue)
top = sorted(finds.items(), key=lambda x: -x[1])[:8]
print("топ по находкам:", top)
