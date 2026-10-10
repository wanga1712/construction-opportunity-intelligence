"""Показать шапки pdf-таблиц у закупок, которые остались без сметы."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.direct_document_extractor import _cache_file, _is_junk

MAX_PIDS = int(os.getenv("PROBE_PIDS", "4"))

rows = [json.loads(l) for l in open("/tmp/direct_batch.jsonl", encoding="utf-8") if l.strip()]
targets = [r for r in rows if not r.get("spec")
           and any(r.get("exts", {}).get(e) for e in ("pdf", "doc", "xls"))][:MAX_PIDS]
print("targets:", [(r["pid"], r.get("exts")) for r in targets])

kw = dict(require_crm_db_connect_kwargs())
di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    for row in targets:
        pid = row["pid"]
        with di.cursor() as cur:
            cur.execute(
                """SELECT local_path FROM document_files
                   WHERE procurement_id=%s AND download_status='COMPLETED' AND local_path IS NOT NULL""",
                (pid,),
            )
            paths = [r[0] for r in cur.fetchall()]
        print("=== pid %s files=%s" % (pid, len(paths)))
        for path in paths:
            if not path or _is_junk(path) or not path.lower().endswith((".pdf", ".doc")):
                continue
            cache = _cache_file(path)
            if not os.path.exists(cache):
                print("   %s | no cache" % os.path.basename(path))
                continue
            with open(cache, encoding="utf-8") as fh:
                doc = json.load(fh)
            tables = doc.get("tables") or []
            print("   %s | tables=%d lines=%d err=%s" % (
                os.path.basename(path), len(tables), len(doc.get("lines") or []), doc.get("error")))
            for table in tables[:5]:
                head = " | ".join(c for c in (table[0] if table else []) if c)[:200]
                print("      rows=%d head=%s" % (len(table), head))
finally:
    di.close()
