"""Что показывает вкладка «Обзор» и что можно взять из документов (светильник/сервер)."""
import json
import os
import re
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.db_bootstrap import connect_databases
from src.services.direct_document_extractor import load_direct_extraction
from src.services.procurement_card_dossier_service import load_procurement_dossier
from src.ui.procurement_card_direct import build_state

for pid in (459670, 459631):
    _r, _t, crm_db, _w = connect_databases()
    dossier = load_procurement_dossier(crm_db, pid)
    extraction = load_direct_extraction(pid)
    state = build_state(extraction, dossier)
    md = dossier.get("money_and_dates") or {}
    print("=== pid %s ===" % pid)
    print("  обзор сейчас: НМЦК=%s | обеспечение=%s | гарантия=%s | исполнение %s..%s | находки=%s | возможностей=%s" % (
        md.get("initial_price"), md.get("guarantee_amount"), md.get("warranty_size"),
        md.get("execution_start_at") or md.get("delivery_start_date"),
        md.get("execution_end_at") or md.get("delivery_end_date"),
        (dossier.get("counts") or {}).get("findings"),
        (dossier.get("counts") or {}).get("opportunities")))
    print("  режим: %s" % json.dumps(state["classified"]["mode"], ensure_ascii=False, default=str))

    money, percent = [], []
    warranty, dates = [], []
    for record in state["classified"]["buckets"]["security"]:
        text = str(record.get("text") or "")
        for match in re.finditer(r"(\d[\d\s\u00a0]{3,})(?:\s*\([^)]*\))?\s*руб", text, re.I):
            value = int(re.sub(r"\D", "", match.group(1)))
            if value >= 1000:
                money.append((value, text[:90]))
        for match in re.finditer(r"(\d{1,2}(?:[.,]\d+)?)\s*%", text):
            percent.append((float(match.group(1).replace(",", ".")), text[:90]))
        if "гарант" in text.lower():
            warranty.append(text[:120])
    for record in state["classified"]["buckets"]["delivery"]:
        text = str(record.get("text") or "")
        if "гарант" in text.lower():
            warranty.append(text[:120])
        if record.get("deadline"):
            dates.append((record.get("deadline"), text[:100]))
    print("  из документов: суммы обеспечения=%s" % sorted({m[0] for m in money}, reverse=True)[:4])
    print("     проценты=%s" % sorted({p[0] for p in percent}, reverse=True)[:4])
    print("     гарантия строк=%d, сроки=%s" % (len(warranty), [d[0] for d in dates]))
    for item in sorted(money, reverse=True)[:2]:
        print("     пример суммы: %s" % item[1])
    for text in warranty[:2]:
        print("     пример гарантии: %s" % text)
