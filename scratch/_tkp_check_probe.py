"""Проверка ТКП: состав разделов и отсутствие требований к участнику/обеспечению."""
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.db_bootstrap import connect_databases
from src.services.direct_document_extractor import load_direct_extraction
from src.services.procurement_card_dossier_service import load_procurement_dossier
from src.ui.procurement_card_direct import build_state

PID = int(os.getenv("CARD_PID", "459631"))

_r, _t, crm_db, _w = connect_databases()
dossier = load_procurement_dossier(crm_db, PID)
extraction = load_direct_extraction(PID)
state = build_state(extraction, dossier)

from src.services.direct_document_extractor import build_tkp_request

delivery = [r.get("text") for r in state["classified"]["buckets"]["delivery"]]
tkp = build_tkp_request(extraction, dossier, delivery_lines=delivery,
                        estimate_rows=state["estimate"]["rows"])
print("tkp_chars=%d lines=%d" % (len(tkp), tkp.count("\n") + 1))
print("--- head ---")
print("\n".join(tkp.split("\n")[:14]))
checks = {
    "позиции сметы": "1. Позиции сметы (1)",
    "сервер": "Сервер вычислительный",
    "ориентировочно из НМЦК": "ориентировочно из НМЦК",
    "техпараметры": "2. Технические параметры (98)",
    "требования к товару": "3. Требования к товару и поставке",
    "условия поставки": "4. Условия поставки",
    "сертификаты": "5. Сертификаты",
    "НЕТ участника": "Требования к участнику",
    "НЕТ обеспечения": "Обеспечение",
}
for label, needle in checks.items():
    print("   %-26s %s" % (label, needle in tkp))
