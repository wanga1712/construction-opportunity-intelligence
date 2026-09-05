#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

echo "=== PHASE 6E: APPLY BATCH FIX ==="

# First: show the lines we need to replace (462-494)
echo "--- CURRENT CODE (lines 462-494) ---"
sed -n '462,494p' src/services/expert_annotation_service.py

# Now patch: replace both load_subcategories and load_subcategories_for_categories
# with batch-correct versions using the real schema (category_id JOIN)
cat > /tmp/_patch_subcategories.py << 'PYEOF'
import sys

filepath = sys.argv[1]
with open(filepath, 'r') as f:
    content = f.read()

old_load_subcategories = '''def load_subcategories(category_code: str, crm_db: Any) -> list[dict]:
    """Return subcategories for *category_code* ordered by name.

    Each item: {code, name}
    """
    try:
        rows = crm_db.execute_query(
            """
            SELECT subcategory_code, subcategory_name
            FROM crm_product_subcategories
            WHERE category_code = %s
            ORDER BY subcategory_name
            """,
            (category_code,),
        )
        return [{"code": r["subcategory_code"], "name": r["subcategory_name"]} for r in (rows or [])]
    except Exception as exc:
        logger.warning("load_subcategories failed for %s: %s", category_code, exc)
        return []


def load_subcategories_for_categories(
    category_codes: list[str], crm_db: Any
) -> dict[str, list[dict]]:
    """Batch subcategory lookup for selected category codes (no per-widget N+1 invent)."""
    out: dict[str, list[dict]] = {}
    for code in category_codes or []:
        text = str(code or "").strip()
        if text:
            out[text] = load_subcategories(text, crm_db)
    return out'''

new_load_subcategories = '''def load_subcategories(category_code: str, crm_db: Any) -> list[dict]:
    """Return subcategories for *category_code* ordered by name.

    Each item: {code, name}
    Uses JOIN through crm_product_categories.id = crm_product_subcategories.category_id.
    """
    try:
        rows = crm_db.execute_query(
            """
            SELECT sc.subcategory_code, sc.subcategory_name
            FROM crm_product_subcategories sc
            JOIN crm_product_categories c ON c.id = sc.category_id
            WHERE c.category_code = %s
            ORDER BY sc.subcategory_name
            """,
            (category_code,),
        )
        return [{"code": r["subcategory_code"], "name": r["subcategory_name"]} for r in (rows or [])]
    except Exception as exc:
        logger.warning("load_subcategories failed for %s: %s", category_code, exc)
        return []


def load_subcategories_for_categories(
    category_codes: list[str], crm_db: Any
) -> dict[str, list[dict]]:
    """Batch subcategory lookup — single SQL query for all requested codes."""
    codes = [str(c or "").strip() for c in (category_codes or []) if str(c or "").strip()]
    if not codes:
        return {}
    try:
        rows = crm_db.execute_query(
            """
            SELECT c.category_code, sc.subcategory_code, sc.subcategory_name
            FROM crm_product_subcategories sc
            JOIN crm_product_categories c ON c.id = sc.category_id
            WHERE c.category_code = ANY(%s)
            ORDER BY c.category_code, sc.subcategory_name
            """,
            (codes,),
        )
        out: dict[str, list[dict]] = {code: [] for code in codes}
        for r in (rows or []):
            cat = r["category_code"]
            if cat in out:
                out[cat].append({"code": r["subcategory_code"], "name": r["subcategory_name"]})
        return out
    except Exception as exc:
        logger.warning("load_subcategories_for_categories batch failed: %s", exc)
        return {code: [] for code in codes}'''

if old_load_subcategories in content:
    content = content.replace(old_load_subcategories, new_load_subcategories)
    with open(filepath, 'w') as f:
        f.write(content)
    print("PATCH_APPLIED=YES")
else:
    print("PATCH_APPLIED=NO (old pattern not found exactly)")
    # Try to find the functions for debugging
    if 'def load_subcategories(' in content:
        print("load_subcategories function exists but text differs")
    if 'def load_subcategories_for_categories(' in content:
        print("load_subcategories_for_categories function exists but text differs")
PYEOF

/opt/CRM_Streamlit/.venv313/bin/python /tmp/_patch_subcategories.py src/services/expert_annotation_service.py

echo "--- Verify patched functions ---"
grep -n 'def load_subcategor' src/services/expert_annotation_service.py
grep -n 'ANY(%s)' src/services/expert_annotation_service.py

echo "--- Test import after patch ---"
PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python -c "
import sys
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
from src.services.expert_annotation_service import load_subcategories_for_categories, load_subcategories
print('IMPORT_AFTER_PATCH=OK')
import inspect
print(inspect.getsource(load_subcategories_for_categories))
" 2>&1

echo "PHASE_6E=DONE"
