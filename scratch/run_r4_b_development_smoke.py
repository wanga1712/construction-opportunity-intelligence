import sys
import os
import json
import hashlib
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('/opt/CRM_Streamlit/.env')
sys.path.insert(0, '/opt/CRM_Streamlit')

from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.r4_input_selector import get_r4_input_candidates
from tender_documents_research.document_processor.structured_fact_extractor import StructuredFactExtractor
from tender_documents_research.document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

doc_conn = get_doc_db_connection()
candidates = get_r4_input_candidates(doc_conn)
doc_conn.close()

print(f"Total canonical extraction_eligible candidates found: {len(candidates)}")

# 1. Freeze up to 5 diverse candidates
frozen_candidates = candidates[:5]

manifest_data = []
for c in frozen_candidates:
    manifest_data.append({
        "detail_id": c["detail_id"],
        "procurement_id": c["procurement_id"],
        "category_code": c["category_code"],
        "subcategory_code": c.get("subcategory_code"),
        "document_name": c.get("document_name"),
        "source_text_sha256": c["source_text_sha256"],
        "source_length": len(c["source_text_snapshot"]),
    })

manifest_str = json.dumps(manifest_data, indent=2, ensure_ascii=False)
manifest_path = "/tmp/r4_b_extractor_smoke_manifest.json"
with open(manifest_path, "w", encoding="utf-8") as f:
    f.write(manifest_str)

manifest_sha256 = hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()
print(f"Manifest written to {manifest_path} (SHA256: {manifest_sha256})")

# 2. Run model inference for each frozen row exactly once
taxonomy_loader = CrmTaxonomyLoader()
extractor = StructuredFactExtractor(taxonomy_loader=taxonomy_loader)

smoke_results = []
metrics = {
    "SMOKE_ROWS": len(frozen_candidates),
    "MODEL_CALLS": 0,
    "COMPLETE": 0,
    "EMPTY": 0,
    "ERROR": 0,
    "ENTITIES_TOTAL": 0,
    "ATTRIBUTES_TOTAL": 0,
    "CONTRACT_VALIDATION_FAILURES": 0,
    "INVALID_JSON": 0,
    "WRONG_MODEL": 0,
    "MODEL_EXCEPTIONS": 0,
}

print("\nExecuting bounded model calls on 5 frozen candidates...")
for idx, c in enumerate(frozen_candidates, 1):
    print(f"[{idx}/{len(frozen_candidates)}] Processing detail_id {c['detail_id']} ({c['category_code']} -> {c.get('subcategory_code')})...")
    metrics["MODEL_CALLS"] += 1
    
    run = extractor.extract_candidate(c)
    
    status = run.status
    if status == "COMPLETE":
        metrics["COMPLETE"] += 1
    elif status == "EMPTY":
        metrics["EMPTY"] += 1
    else:
        metrics["ERROR"] += 1
        code = run.error_code or ""
        if "CONTRACT_VALIDATION_FAILED" in code:
            metrics["CONTRACT_VALIDATION_FAILURES"] += 1
        elif "INVALID_JSON" in code:
            metrics["INVALID_JSON"] += 1
        elif "WRONG_MODEL" in code:
            metrics["WRONG_MODEL"] += 1
        elif "MODEL_EXCEPTION" in code:
            metrics["MODEL_EXCEPTIONS"] += 1

    ent_count = len(run.entities)
    metrics["ENTITIES_TOTAL"] += ent_count
    
    entities_summary = []
    for ent in run.entities:
        attr_count = len(ent.attributes)
        metrics["ATTRIBUTES_TOTAL"] += attr_count
        
        attrs_list = [
            {
                "name": a.attribute_name,
                "raw_value": a.raw_value,
                "numeric_value": a.numeric_value,
                "unit_raw": a.unit_raw,
                "quote": a.source_quote,
            }
            for a in ent.attributes
        ]
        entities_summary.append({
            "entity_type": ent.entity_type,
            "product_name_raw": ent.product_name_raw,
            "manufacturer_raw": ent.manufacturer_raw,
            "brand_raw": ent.brand_raw,
            "product_line_raw": ent.product_line_raw,
            "model_article_raw": ent.model_article_raw,
            "quantity_raw": ent.quantity_raw,
            "quantity_value": ent.quantity_value,
            "quantity_unit_raw": ent.quantity_unit_raw,
            "unit_price_raw": ent.unit_price_raw,
            "unit_price_value": ent.unit_price_value,
            "total_price_raw": ent.total_price_raw,
            "total_price_value": ent.total_price_value,
            "currency_raw": ent.currency_raw,
            "currency_code": ent.currency_code,
            "attributes": attrs_list,
            "source_quote": ent.source_quote,
        })

    row_result = {
        "detail_id": c["detail_id"],
        "procurement_id": c["procurement_id"],
        "category_code": c["category_code"],
        "subcategory_code": c.get("subcategory_code"),
        "status": status,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "entity_count": ent_count,
        "entities": entities_summary,
        "raw_response": run.raw_response,
    }
    smoke_results.append(row_result)

results_str = json.dumps(smoke_results, indent=2, ensure_ascii=False)
results_path = "/tmp/r4_b_extractor_smoke_results.json"
with open(results_path, "w", encoding="utf-8") as f:
    f.write(results_str)

results_sha256 = hashlib.sha256(results_str.encode("utf-8")).hexdigest()
print(f"\nResults written to {results_path} (SHA256: {results_sha256})")

print("\n" + "=" * 80)
print("BOUNDED DEVELOPMENT SMOKE METRICS:")
print("=" * 80)
for k, v in metrics.items():
    print(f"  {k}: {v}")

print("\n" + "=" * 80)
print("DETAILED SMOKE ROWS REPORT:")
print("=" * 80)
for res in smoke_results:
    print(f"\n--- DETAIL ID {res['detail_id']} ({res['category_code']} -> {res['subcategory_code']}) ---")
    print(f"  STATUS: {res['status']}")
    if res['error_code']:
        print(f"  ERROR_CODE: {res['error_code']}")
        print(f"  ERROR_MSG: {res['error_message']}")
    print(f"  ENTITIES COUNT: {res['entity_count']}")
    for e_idx, ent in enumerate(res['entities'], 1):
        print(f"    [Entity {e_idx}] Type: {ent['entity_type']} | Name: '{ent['product_name_raw']}'")
        print(f"      Manufacturer: {ent['manufacturer_raw']} | Brand: {ent['brand_raw']} | Model: {ent['model_article_raw']}")
        print(f"      Quantity: {ent['quantity_raw']} (Value: {ent['quantity_value']}) | Unit: {ent['quantity_unit_raw']}")
        print(f"      Unit Price: {ent['unit_price_raw']} (Value: {ent['unit_price_value']}) | Total: {ent['total_price_raw']} | Currency: {ent['currency_code']}")
        print(f"      Attributes ({len(ent['attributes'])}): {ent['attributes']}")
        print(f"      Anchor Quote: '{ent['source_quote']}'")
