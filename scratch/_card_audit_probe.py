"""Аудит распределения извлечённых данных прямой поставки (до/после классификации)."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.db_bootstrap import connect_databases
from src.services.direct_document_extractor import load_direct_extraction
from src.services.direct_estimate_table import build_estimate
from src.services.direct_requirement_classifier import PRODUCT_GROUPS, classify
from src.services.procurement_card_dossier_service import load_procurement_dossier

PID = int(os.getenv("CARD_PID", "459631"))


def jdump(value):
    return json.dumps(value, ensure_ascii=False, default=str)

_r, _t, crm_db, warn = connect_databases()
dossier = load_procurement_dossier(crm_db, PID)
extraction = load_direct_extraction(PID)

raw_counts = {
    "spec": len(extraction.get("spec") or []),
    "tech": len(extraction.get("tech") or []),
    "requirements": len(extraction.get("requirements") or []),
    "sections": {k: len(v or []) for k, v in (extraction.get("sections") or {}).items()},
    "terms": len(extraction.get("terms") or []),
}
raw_counts["sections_total"] = sum(raw_counts["sections"].values())
raw_counts["displayed_old_counter"] = (raw_counts["requirements"] + raw_counts["sections_total"])
print("RAW:", jdump(raw_counts))

result = classify(extraction, dossier)
print("MODE:", jdump(result["mode"]))
print("COUNTS:", jdump(result["counts"]))
print("AUDIT:", jdump(result["audit"]))
print("GROUPS:", jdump(result["groups"]))
print("GROUP_TITLES:", jdump({k: t for k, t, _ in PRODUCT_GROUPS}))

for key in ("estimate", "product", "delivery", "participant", "security", "additional", "unclassified"):
    items = result["buckets"][key]
    print("--- %s (%d) ---" % (key, len(items)))
    for item in items[:3]:
        print("   %s [%s] %s" % (item["id"], item.get("source_file"), (item.get("text") or item.get("param") or "")[:110]))

estimate = build_estimate(extraction, nmck=(dossier.get("money_and_dates") or {}).get("initial_price"))
print("--- ESTIMATE TABLE ---")
for row in estimate["rows"][:8]:
    print("   %s | okpd=%s | qty=%s %s | price=%s (%s) | sum=%s (%s)" % (
        row["name"][:60], row["okpd"], row["qty"], row["unit"], row["unit_price"],
        row["unit_price_source"], row["sum"], row["sum_source"]))
print("TOTALS:", jdump(estimate["totals"]))
print("COLUMNS_NOT_SHOWN:", jdump(estimate["columns_not_shown"]))
print("LOSSES: input=%s output=%s" % (result["audit"]["input_total"], result["audit"]["output_total"]))
