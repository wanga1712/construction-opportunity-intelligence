"""Проверка ИИ-нормализации срока поставки на реальной закупке."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.direct_document_extractor import (
    extract_delivery_terms,
    load_direct_extraction,
    normalize_delivery_terms,
)

PID = int(os.getenv("TERMS_PID", "459631"))

ext = load_direct_extraction(PID)
terms = ext.get("terms") or []
print("pid=%s terms=%d" % (PID, len(terms)))
for term in terms:
    print("  raw: %s" % term["text"][:150])
    print("  det: deadline=%s duration=%s/%s anchor=%s" % (
        term.get("deadline"), term.get("duration_value"), term.get("duration_unit"),
        term.get("anchor")))

normalized = normalize_delivery_terms(terms)
print("--- model output (%d) ---" % len(normalized))
for item in normalized:
    print(json.dumps(item, ensure_ascii=False)[:300])
