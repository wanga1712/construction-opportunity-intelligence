"""Retrieve and print 5 real product findings in exact requested format."""
import os
import sys
import json
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("verify_extracted_products")

def main():
    _, _, crm_db, _ = connect_databases()
    
    # Select some findings with non-empty quantity and unit
    rows = crm_db.execute_query(
        """
        SELECT f.*, t.consensus_state
        FROM crm_v3_product_findings f
        LEFT JOIN crm_v3_autonomous_analysis_traces t ON t.procurement_id = f.procurement_id
        WHERE f.quantity IS NOT NULL AND f.unit IS NOT NULL AND f.unit != ''
        LIMIT 5
        """
    )
    
    # If not enough, select any findings
    if len(rows) < 5:
        logger.warning(f"Only found {len(rows)} findings with quantity/unit. Fetching others to make 5.")
        more_rows = crm_db.execute_query(
            """
            SELECT f.*, t.consensus_state
            FROM crm_v3_product_findings f
            LEFT JOIN crm_v3_autonomous_analysis_traces t ON t.procurement_id = f.procurement_id
            LIMIT %s
            """,
            (5 - len(rows),)
        )
        rows.extend(more_rows)
        
    print(f"====== REAL PRODUCT EVIDENCE OUTPUT ======")
    for i, r in enumerate(rows, 1):
        print(f"\n--- PRODUCT EXAMPLE {i} ---")
        print(f"PROCUREMENT_NUMBER={r.get('procurement_number')}")
        print(f"CATEGORY={r.get('category_code')}")
        print(f"SUBCATEGORY=NULL")  # We don't have separate subcategory in crm_v3_product_findings
        print(f"PRODUCT={r.get('product_name_normalized')}")
        print(f"BRAND={r.get('brand')}")
        print(f"MODEL={r.get('model')}")
        print(f"ARTICLE=NULL")      # We don't have article column, so it is NULL
        print(f"QUANTITY={r.get('quantity')}")
        print(f"UNIT={r.get('unit')}")
        print(f"UNIT_PRICE=NULL")   # We don't have unit_price column
        print(f"DOCUMENT_NAME={r.get('document_name')}")
        print(f"DOCUMENT_URL=NULL")   # Resolver url is compiled on UI side, so it is NULL here
        print(f"PAGE={r.get('page')}")
        print(f"SHEET={r.get('sheet')}")
        print(f"ROW={r.get('row_num')}")
        print(f"POSITION_NUMBER={r.get('position_number')}")
        print(f"EVIDENCE_TEXT={r.get('evidence_text')}")
        
        # Check Hunter vs Auditor values
        role = r.get("extractor_role")
        if role == "HUNTER":
            print(f"HUNTER_VALUE={r.get('product_type') or r.get('product_name_normalized')}")
            # Try to query Auditor value for same product
            aud_rows = crm_db.execute_query(
                "SELECT product_type FROM crm_v3_product_findings WHERE procurement_id = %s AND product_name_normalized = %s AND extractor_role = 'AUDITOR'",
                (r.get("procurement_id"), r.get("product_name_normalized"))
            )
            aud_val = aud_rows[0]["product_type"] if aud_rows else "NULL"
            print(f"AUDITOR_VALUE={aud_val}")
        else:
            # Try to query Hunter value for same product
            hunt_rows = crm_db.execute_query(
                "SELECT product_type FROM crm_v3_product_findings WHERE procurement_id = %s AND product_name_normalized = %s AND extractor_role = 'HUNTER'",
                (r.get("procurement_id"), r.get("product_name_normalized"))
            )
            hunt_val = hunt_rows[0]["product_type"] if hunt_rows else "NULL"
            print(f"HUNTER_VALUE={hunt_val}")
            print(f"AUDITOR_VALUE={r.get('product_type') or r.get('product_name_normalized')}")
            
        print(f"CONSENSUS={r.get('consensus_state')}")

if __name__ == "__main__":
    main()
