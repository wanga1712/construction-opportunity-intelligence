"""Evaluate special cases 165114 and 78763 with Phase 5.2 Second Pass."""
from __future__ import annotations

import json
import logging
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, "/opt/CRM_Streamlit" if os.path.exists("/opt/CRM_Streamlit") else os.path.abspath("."))

import psycopg2
from scripts.run_second_pass_calibration_v2 import load_procurement_meta, run_evaluation_item

def main():
    conn_di = psycopg2.connect("dbname=document_intelligence user=postgres")
    conn_crm = psycopg2.connect("dbname=crm user=postgres")

    target_pids = [165114, 78763]
    proc_map = load_procurement_meta(conn_crm, target_pids)

    print("=== EVALUATING SPECIAL CASES (165114 & 78763) ===")
    for pid in target_pids:
        proc = proc_map.get(pid)
        if not proc:
            print(f"Procurement {pid} not found in CRM metadata!")
            continue
        print(f"\n--- EVALUATING CRM_ID={pid} ---")
        ev = run_evaluation_item(conn_di, conn_crm, proc)
        print(f"Model Medal: {ev['model_medal']} (Score: {ev['model_score']}) | Facts: {ev['findings_count']} | EvRefs: {ev['evidence_refs_count']}")
        print(f"Reason: {ev['model_reason']}")
        print("Categories:")
        for ce in ev.get("parsed", {}).get("category_evaluations", []):
            print(f"  * {ce.get('category_code')}: Medal={ce.get('category_model_medal')} Score={ce.get('category_model_score')} EvRefs={len(ce.get('evidence_refs', []))}")
        print("Facts:")
        for f in ev.get("findings_diag", []):
            print(f"  * Fact: '{f['product_name']}' (Cat: {f['category']}) | Quote: '{f['source_quote']}' | Supp: {f['support_type']} | Match={f['is_supported']}")

if __name__ == "__main__":
    main()
