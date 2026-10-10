"""Поставить конкретную закупку в документную очередь (та же функция, что у кнопки в карточке)."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.db_bootstrap import connect_databases
from src.services.procurement_card_dossier_service import queue_procurement_for_documents

PID = int(os.getenv("ENQUEUE_PID", "456559"))
APPLY = os.getenv("ENQUEUE_APPLY", "0") == "1"

_r, _t, crm_db, _w = connect_databases()
if not APPLY:
    print("DRY-RUN: поставлю в очередь pid=%s (ENQUEUE_APPLY=1 для применения)" % PID)
    raise SystemExit(0)

result = queue_procurement_for_documents(crm_db, PID)
print("queue_procurement_for_documents ->", result)

kw = dict(require_crm_db_connect_kwargs())
di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with di.cursor() as cur:
        cur.execute(
            """SELECT id, status, queue_lane, priority_score, created_at
               FROM document_processing_queue WHERE procurement_id=%s ORDER BY id DESC LIMIT 3""",
            (PID,),
        )
        for row in cur.fetchall():
            print("   строка очереди:", row)
finally:
    di.close()
