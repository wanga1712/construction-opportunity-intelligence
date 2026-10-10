"""Проверка сборки карточки на разных DIRECT-закупках + поиск светотехники."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.db_bootstrap import connect_databases
from src.services.direct_document_extractor import load_direct_extraction
from src.services.procurement_card_dossier_service import load_procurement_dossier
from src.ui.procurement_card_direct import build_state

SAMPLE = int(os.getenv("SAMPLE", "20"))
LIGHT_HINT = ("свет", "light", "led", "лампа", "светильник", "электро")

rows = [json.loads(l) for l in open("/tmp/direct_batch.jsonl", encoding="utf-8") if l.strip()]
with_data = [r for r in rows if r.get("spec") or r.get("tech")]
sample = with_data[:SAMPLE]

print("--- срок поставки pid 459631 (после нормализации) ---")
ext = load_direct_extraction(459631)
for term in ext.get("terms") or []:
    print("  deadline=%s dur=%s anchor=%s variants=%d sources=%s" % (
        term.get("deadline"), term.get("duration_value"), term.get("anchor"),
        len(term.get("variants") or []), term.get("sources")))
    print("     text: %s" % term["text"][:120])
    for variant in (term.get("variants") or [])[:3]:
        print("     variant: %s" % variant[:110])

_r, _t, crm_db, _w = connect_databases()
print("--- сборка карточки на %d DIRECT-закупках ---" % len(sample))
header = "%-8s %-16s %6s %6s %6s %6s %6s %6s %6s" % (
    "pid", "scope", "spec", "prod", "deliv", "part", "sec", "add", "terms")
print(header)
totals = {"with_spec": 0, "with_terms": 0, "with_price": 0, "errors": 0}
for row in sample:
    pid = row["pid"]
    try:
        dossier = load_procurement_dossier(crm_db, pid)
        extraction = load_direct_extraction(pid)
        state = build_state(extraction, dossier)
        counts = state["classified"]["counts"]
        positions = len(state["estimate"]["rows"])
        priced = sum(1 for r in state["estimate"]["rows"] if r.get("unit_price"))
        scope = (state["classified"]["mode"] or {}).get("scope_type") or "-"
        print("%-8s %-16s %6d %6d %6d %6d %6d %6d %6d" % (
            pid, scope, positions, counts["product"], counts["delivery"],
            counts["participant"], counts["security"], counts["additional"],
            len(extraction.get("terms") or [])))
        totals["with_spec"] += 1 if positions else 0
        totals["with_terms"] += 1 if extraction.get("terms") else 0
        totals["with_price"] += 1 if priced else 0
    except Exception as exc:  # noqa: BLE001
        totals["errors"] += 1
        print("%-8s ERROR %s: %s" % (pid, type(exc).__name__, str(exc)[:80]))
print("итоги: %s" % totals)

kw = dict(require_crm_db_connect_kwargs())
conn = psycopg2.connect(**kw)
try:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT o.procurement_id, p.contract_number, o.commercial_category_code,
                      count(*) FILTER (WHERE upper(coalesce(o.opportunity_track,''))='DIRECT_SUPPLY')
               FROM crm_procurement_category_opportunities o
               JOIN crm_procurements p ON p.id = o.procurement_id
               WHERE o.commercial_category_code ILIKE ANY(%s)
               GROUP BY 1,2,3
               HAVING count(*) FILTER (WHERE upper(coalesce(o.opportunity_track,''))='DIRECT_SUPPLY') > 0
               ORDER BY 1 DESC LIMIT 15""",
            (["%" + h + "%" for h in LIGHT_HINT],),
        )
        found = cur.fetchall()
    print("--- DIRECT-закупки со «светом» в категории: %d ---" % len(found))
    for row in found:
        print("   pid=%s number=%s category=%s" % row[:3])
    with conn.cursor() as cur:
        cur.execute("select distinct commercial_category_code from crm_procurement_category_opportunities order by 1")
        cats = [r[0] for r in cur.fetchall()]
    print("--- категории в реестре (%d) ---" % len(cats))
    print("   " + ", ".join(cats))
finally:
    conn.close()
