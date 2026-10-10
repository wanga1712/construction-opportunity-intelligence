"""Почему карточка 456559 пустая: что видит досье и есть ли строка очереди."""
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.db_bootstrap import connect_databases
from src.services.procurement_card_dossier_service import load_procurement_dossier

PID = 456559

_r, _t, crm_db, _w = connect_databases()
dossier = load_procurement_dossier(crm_db, PID)
print("counts:", dossier.get("counts"))
print("opportunities:", dossier.get("opportunities"))
print("documents:", len(dossier.get("documents") or []))
print("findings:", len(dossier.get("findings") or []))
print("supply_candidates:", len(dossier.get("supply_candidates") or []))

kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**kw)
try:
    cur = conn.cursor()
    cur.execute("select count(*) from crm_procurement_category_opportunities where procurement_id=%s", (PID,))
    print("возможностей в CRM:", cur.fetchone()[0])
finally:
    conn.close()

di = psycopg2.connect(dbname="document_intelligence", **{k: v for k, v in kw.items() if k != "dbname"})
try:
    cur = di.cursor()
    cur.execute("select count(*) from document_processing_queue where procurement_id=%s", (PID,))
    print("строк очереди:", cur.fetchone()[0])
    cur.execute("select count(*) from document_files where procurement_id=%s", (PID,))
    print("строк файлов:", cur.fetchone()[0])
finally:
    di.close()
