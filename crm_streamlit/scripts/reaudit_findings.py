"""Re-audit existing product findings in crm_v3_product_findings."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.bootstrap import setup_source_path
setup_source_path()

from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    
    # 1. Load active category codes
    cats = crm_db.execute_query("SELECT category_code FROM crm_product_categories WHERE is_active = TRUE") or []
    active_codes = {c["category_code"] for c in cats}
    
    # 2. Fetch all findings
    findings = crm_db.execute_query("SELECT id, category_code, product_type, product_name_normalized FROM crm_v3_product_findings") or []
    
    for f in findings:
        fid = f["id"]
        cat_code = f["category_code"]
        
        # If the category is not active
        if cat_code not in active_codes:
            validation_status = "INVALID_NOT_IN_REGISTRY"
            resolved_cat = None
            
            # Attempt keyword lookup resolution
            prod_type_lower = str(f.get("product_type") or "").lower()
            prod_name_lower = str(f.get("product_name_normalized") or "").lower()
            
            for code in active_codes:
                if code in prod_type_lower or code in prod_name_lower:
                    resolved_cat = code
                    validation_status = "RESOLVED"
                    break
            
            # Update finding
            crm_db.execute_update(
                """
                UPDATE crm_v3_product_findings
                SET category_code = %s,
                    raw_model_category_code = %s,
                    category_validation_status = %s
                WHERE id = %s
                """,
                (resolved_cat, cat_code, validation_status, fid)
            )
        else:
            # Set VALID status and raw category for already valid ones
            crm_db.execute_update(
                """
                UPDATE crm_v3_product_findings
                SET raw_model_category_code = %s,
                    category_validation_status = 'VALID'
                WHERE id = %s
                """,
                (cat_code, fid)
            )
            
    print("Re-audit completed successfully.")

if __name__ == "__main__":
    main()
