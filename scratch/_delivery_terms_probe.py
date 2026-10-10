"""Какие формулировки о сроке поставки реально есть в документах закупки."""
import os
import re
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.direct_document_extractor import _external_docs, _docx_paragraphs, _is_junk, _docx_tables

PID = int(os.getenv("TERMS_PID", "459631"))
MARKERS = ("срок поставки", "сроки поставки", "срок исполнения", "срок оказания",
           "поставка осуществляется", "сроки поставки товара", "не позднее",
           "в течение", "с даты подписания", "с момента подписания")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT local_path FROM document_files
               WHERE procurement_id=%s AND local_path IS NOT NULL""",
            (PID,),
        )
        paths = [r[0] for r in cur.fetchall()]
finally:
    conn.close()

external = _external_docs(paths)
print("pid=%s files=%d external=%d" % (PID, len(paths), len(external)))
hits = 0
for path in paths:
    if not path or _is_junk(path):
        continue
    doc = external.get(path)
    if doc is not None:
        lines = [str(x) for x in (doc.get("lines") or [])]
    elif path.lower().endswith(".docx") and os.path.exists(path):
        lines = _docx_paragraphs(path)
    else:
        lines = []
    if not lines and path.lower().endswith(".docx") and os.path.exists(path):
        lines = [" ".join(row) for table in _docx_tables(path) for row in table]
    for line in lines:
        low = line.lower()
        if any(marker in low for marker in MARKERS) and re.search(r"\d", low):
            hits += 1
            if hits <= 25:
                print("   [%s] %s" % (os.path.basename(path)[:28], line[:220]))
print("всего строк-кандидатов: %d" % hits)
