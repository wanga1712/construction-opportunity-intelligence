"""Показать строки ТЗ-xlsx (ищем настоящую шапку характеристик)."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.direct_document_extractor import _external_docs

PID = int(os.getenv("PROBE_PID", "459924"))
SUFFIX = os.getenv("PROBE_SUFFIX", ".xlsx")
KW = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in KW.items() if k != "dbname"})
try:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT local_path FROM document_files
               WHERE procurement_id=%s AND download_status='COMPLETED' AND local_path IS NOT NULL""",
            (PID,))
        paths = [r[0] for r in cur.fetchall()]
finally:
    conn.close()

external = _external_docs(paths)
for path in paths:
    if not path or not path.lower().endswith(SUFFIX):
        continue
    print("=== %s" % os.path.basename(path))
    doc = external.get(path) or {}
    for t_index, table in enumerate(doc.get("tables") or [], 1):
        print("--- таблица %d (строк %d) ---" % (t_index, len(table)))
        for i, row in enumerate(table[:28], 1):
            cells = [c for c in row if c]
            if not cells:
                continue
            print("%3d | %s" % (i, " | ".join(c[:60] for c in cells)[:200]))
