"""Audit script to retrieve and analyze Hunter-Auditor consensus outputs on S13."""
import os
import sys
import json
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("audit_consensus")

def main():
    logger.info("Connecting to database...")
    _, _, crm_db, _ = connect_databases()
    
    rows = crm_db.execute_query(
        """
        SELECT t.procurement_id, t.consensus_state,
               h.validated_model_result as hunter_res,
               a.validated_model_result as auditor_res
        FROM crm_v3_autonomous_analysis_traces t
        JOIN crm_v3_model_inference_runs h ON h.id = t.hunter_run_id
        JOIN crm_v3_model_inference_runs a ON a.id = t.auditor_run_id
        """
    )
    
    logger.info(f"Retrieved {len(rows)} trace results from database.")
    
    counts = {
        "OBJECT_VALUE_DIFFERENT": 0,
        "PROCUREMENT_MODE_DIFFERENT": 0,
        "CATEGORY_SCOPE_DIFFERENT": 0,
        "CATEGORY_SET_DIFFERENT": 0,
        "PRODUCT_SET_DIFFERENT": 0,
        "COMMERCIAL_ENTRY_DIFFERENT": 0,
        "MEDAL_DIFFERENT": 0,
        "EVIDENCE_ONLY_DIFFERENCE": 0,
        "CONFIDENCE_ONLY_DIFFERENCE": 0,
        "FORMAT/NORMALIZATION_DIFFERENCE": 0,
    }
    
    for r in rows:
        pid = r["procurement_id"]
        hunter = r["hunter_res"]
        auditor = r["auditor_res"]
        
        if isinstance(hunter, str):
            try: hunter = json.loads(hunter)
            except: hunter = {}
        if isinstance(auditor, str):
            try: auditor = json.loads(auditor)
            except: auditor = {}
            
        # Extract verdicts
        obj = auditor.get("object", {})
        mode = auditor.get("procurement_mode", {})
        scope = auditor.get("category_scope", {})
        comm = auditor.get("commercial_entry", {})
        medal = auditor.get("medal", {})
        cats = auditor.get("categories", [])
        prods = auditor.get("products", [])
        
        # Log details
        logger.info(f"Procurement {pid}:")
        logger.info(f"  Object verdict: {obj.get('verdict')} ({obj.get('why')})")
        logger.info(f"  Mode verdict: {mode.get('verdict')} ({mode.get('why')})")
        logger.info(f"  Scope verdict: {scope.get('verdict')} ({scope.get('why')})")
        logger.info(f"  Comm verdict: {comm.get('verdict')} ({comm.get('why')})")
        logger.info(f"  Medal verdict: {medal.get('verdict')} ({medal.get('why')})")
        
        disagreements = []
        if obj.get("verdict") == "DISAGREE":
            counts["OBJECT_VALUE_DIFFERENT"] += 1
            disagreements.append("OBJECT")
        if mode.get("verdict") == "DISAGREE":
            counts["PROCUREMENT_MODE_DIFFERENT"] += 1
            disagreements.append("MODE")
        if scope.get("verdict") == "DISAGREE":
            counts["CATEGORY_SCOPE_DIFFERENT"] += 1
            disagreements.append("SCOPE")
        if comm.get("verdict") == "DISAGREE":
            counts["COMMERCIAL_ENTRY_DIFFERENT"] += 1
            disagreements.append("COMMERCIAL_ENTRY")
        if medal.get("verdict") == "DISAGREE":
            counts["MEDAL_DIFFERENT"] += 1
            disagreements.append("MEDAL")
            
        # Check category/product disagreements
        cat_disagree = any(c.get("verdict") == "DISAGREE" for c in cats)
        prod_disagree = any(p.get("verdict") == "DISAGREE" for p in prods)
        
        if cat_disagree:
            counts["CATEGORY_SET_DIFFERENT"] += 1
            disagreements.append("CATEGORIES")
        if prod_disagree:
            counts["PRODUCT_SET_DIFFERENT"] += 1
            disagreements.append("PRODUCTS")
            
        # If no explicit disagreements on core or sets, check for other differences
        if not disagreements:
            # Check for partial or other differences
            is_partial = (
                obj.get("verdict") == "PARTIAL" or
                mode.get("verdict") == "PARTIAL" or
                scope.get("verdict") == "PARTIAL" or
                comm.get("verdict") == "PARTIAL" or
                medal.get("verdict") == "PARTIAL" or
                any(c.get("verdict") == "PARTIAL" for c in cats) or
                any(p.get("verdict") == "PARTIAL" for p in prods)
            )
            if is_partial:
                counts["FORMAT/NORMALIZATION_DIFFERENCE"] += 1
            else:
                counts["EVIDENCE_ONLY_DIFFERENCE"] += 1
                
    print("====== AUDIT SUMMARY COUNTS ======")
    for k, v in counts.items():
        print(f"{k}={v}")

if __name__ == "__main__":
    main()
