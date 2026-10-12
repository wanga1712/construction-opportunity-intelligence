"""Diagnostic script to inspect the 6 unsupported findings from Phase 5.1."""
import psycopg2
import json

conn_di = psycopg2.connect("dbname=document_intelligence user=postgres")
conn_crm = psycopg2.connect("dbname=crm user=postgres")

from src.services.second_pass_service import extract_evidence_snippets

cur_crm = conn_crm.cursor()
pids = [164721, 70435, 163995, 164525, 6305, 164506, 66831, 93275, 127854, 104939, 130159, 75907, 65654, 83383, 9441, 40983, 139567, 41334, 22679, 18739, 95712, 163854, 163645, 163638]

unsupported = []
for pid in pids:
    cur_crm.execute("""
        SELECT id, validated_model_result, raw_model_text
        FROM crm_v3_model_inference_runs 
        WHERE procurement_id = %s AND prompt_version = 'v3_second_pass_evidence_7b_v1'
        ORDER BY id DESC LIMIT 1
    """, (pid,))
    row = cur_crm.fetchone()
    if not row or not row[1]:
        continue
    run_id, val, raw = row[0], row[1], row[2]
    snippets, _ = extract_evidence_snippets(conn_di, pid)
    snippet_corpus = " ".join(s["text"].lower() for s in snippets)
    
    for f in val.get("found_facts", []):
        pname = str(f.get("product_name_normalized") or "").strip()
        quote = str(f.get("source_quote") or "").strip()
        doc = str(f.get("document_name") or "").strip()
        
        in_corpus = (
            (quote and quote.lower() in snippet_corpus) or
            (pname and pname.lower() in snippet_corpus) or
            any(word in snippet_corpus for word in pname.lower().split() if len(word) > 4)
        )
        if not in_corpus:
            # Find closest snippet or matching category snippet
            cat = f.get("category_code")
            matching_snips = [s for s in snippets if s["category_code"] == cat]
            if not matching_snips:
                matching_snips = snippets[:2]
            unsupported.append({
                "pid": pid,
                "run_id": run_id,
                "product_name": pname,
                "category": cat,
                "source_quote": quote,
                "document": doc,
                "qty": f.get("quantity"),
                "unit": f.get("unit"),
                "price": f.get("unit_price"),
                "snippets": matching_snips
            })

print(f"=== FOUND {len(unsupported)} UNSUPPORTED FINDINGS ===")
for idx, u in enumerate(unsupported, 1):
    print(f"\n--- [{idx}/{len(unsupported)}] CRM_ID={u['pid']} ---")
    print(f"MODEL_OUTPUT_NAME: '{u['product_name']}'")
    print(f"CATEGORY: {u['category']}")
    print(f"SOURCE_QUOTE: '{u['source_quote']}'")
    print(f"DOCUMENT: '{u['document']}'")
    print(f"QTY/UNIT/PRICE: {u['qty']} {u['unit']} @ {u['price']}")
    print("MATCHING SNIPPETS IN PROMPT:")
    for s in u["snippets"][:3]:
        print(f"  [{s['category_code']}] {s['document_name']} ({s['location']}): '{s['text']}'")
