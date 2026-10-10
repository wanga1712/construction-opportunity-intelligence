"""Сколько документов DIRECT-пула реально лежит на диске (retention уже прошёл)."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

rows = [json.loads(l) for l in open("/tmp/direct_batch.jsonl", encoding="utf-8") if l.strip()]
no_spec = [r["pid"] for r in rows if not r.get("spec")]

kw = dict(require_crm_db_connect_kwargs())
di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with di.cursor() as cur:
        cur.execute(
            """SELECT procurement_id, local_path, local_deleted_at IS NOT NULL AS purged
               FROM document_files
               WHERE download_status='COMPLETED' AND local_path IS NOT NULL
                 AND procurement_id = ANY(%s)""",
            (no_spec,),
        )
        data = cur.fetchall()
finally:
    di.close()

total = missing = purged = present = 0
pids_all_missing = set()
seen_pid = set()
for pid, path, is_purged in data:
    total += 1
    seen_pid.add(pid)
    exists = bool(path) and os.path.exists(path)
    if is_purged:
        purged += 1
    if exists:
        present += 1
    else:
        missing += 1
        pids_all_missing.add(pid)

print("no_spec_pids=%d files_total=%d present_on_disk=%d missing=%d purged_flagged=%d" % (
    len(no_spec), total, present, missing, purged))
print("pids_with_zero_files_on_disk=%d of %d" % (len(pids_all_missing), len(seen_pid)))

# Контроль по всему пулу: сколько закупок реально имеют файлы на диске сейчас.
with_files_now = set()
for row in rows:
    pid = row["pid"]
    if pid in pids_all_missing:
        continue
    with_files_now.add(pid)
print("pool=%d pids_без_файлов=%d pids_с_файлами<=%d" % (
    len(rows), len(pids_all_missing), len(with_files_now)))
covered = sum(1 for r in rows if r.get("spec") or r.get("tech") or r.get("sections"))
print("покрытие по пулу=%d/%d" % (covered, len(rows)))
