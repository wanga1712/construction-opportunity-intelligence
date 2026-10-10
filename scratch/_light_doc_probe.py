"""Что реально лежит в документах по светильнику (таблицы/строки) для pid 459670."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.direct_document_extractor import _is_junk, _tables_for, _external_docs

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 459670
kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT local_path FROM document_files
               WHERE procurement_id=%s AND download_status='COMPLETED' AND local_path IS NOT NULL""",
            (PID,),
        )
        paths = [r[0] for r in cur.fetchall()]
finally:
    conn.close()

external = _external_docs(paths)
print("pid=%s файлов=%d (кэш=%d)" % (PID, len(paths), len(external)))
for path in paths:
    if not path or _is_junk(path):
        continue
    print("=== %s" % os.path.basename(path))
    tables = (external.get(path) or {}).get("tables") or _tables_for(path) if os.path.exists(path) else \
        (external.get(path) or {}).get("tables") or []
    for number, table in enumerate(tables, 1):
        header = " | ".join(c for c in (table[0] if table else []) if c)[:180]
        print("   таблица %d: строк=%d шапка=%s" % (number, len(table), header))
        for row in table[1:4]:
            print("      %s" % " | ".join(c for c in row if c)[:170])
    lines = (external.get(path) or {}).get("lines") or []
    if lines:
        print("   строк текста=%d, пример:" % len(lines))
        for line in lines[:6]:
            print("      %s" % line[:150])
