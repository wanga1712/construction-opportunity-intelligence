#!/usr/bin/env python3
"""Step 2: Inspect production document processor and phrase vocabulary."""
import os, json, sys, subprocess
import psycopg2, psycopg2.extras

crm_conn = psycopg2.connect(
    "dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX host=127.0.0.1 port=5432"
)

def query(conn, sql, params=None):
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return list(cur.fetchall())
    except Exception as e:
        conn.rollback()
        return [{"error": str(e)}]

# All tables
tables = query(crm_conn, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
print("=== CRM TABLES ===")
for t in tables:
    print(" ", t.get("tablename"))

# Check for subcategory tables
subcats = query(crm_conn, "SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE '%subcategor%' OR tablename LIKE '%term%' OR tablename LIKE '%phrase%') ORDER BY tablename")
print("\n=== PHRASE/TERM/SUBCATEGORY TABLES ===")
for t in subcats:
    tname = t.get("tablename")
    print(f"  {tname}")

# Count terms in crm_product_subcategory_terms if exists
for t_row in subcats:
    tname = t_row.get("tablename")
    if tname:
        cnt = query(crm_conn, f"SELECT count(*) AS c FROM {tname}")
        print(f"  {tname}: count={cnt[0].get('c','?') if cnt else '?'}")

# Sample terms
terms_result = query(crm_conn, """
    SELECT c.category_code, s.subcategory_code, t.term_type, t.phrase, t.weight, t.is_active
    FROM crm_product_categories c
    JOIN crm_product_subcategories s ON s.category_id = c.id AND s.is_active = TRUE
    LEFT JOIN crm_product_subcategory_terms t ON t.subcategory_id = s.id AND t.is_active = TRUE
    WHERE c.is_active = TRUE
    ORDER BY c.category_code, s.subcategory_code, t.term_type, t.phrase
    LIMIT 50
""")
print("\n=== SAMPLE TERMS ===")
for r in terms_result:
    print(f"  {r.get('category_code')} / {r.get('subcategory_code')} | {r.get('term_type')} | {r.get('phrase')}")

# Count total active search terms
count_terms = query(crm_conn, """
    SELECT count(*) AS total_terms, count(DISTINCT t.phrase) AS distinct_phrases,
           count(DISTINCT c.category_code) AS categories
    FROM crm_product_categories c
    JOIN crm_product_subcategories s ON s.category_id = c.id AND s.is_active = TRUE
    JOIN crm_product_subcategory_terms t ON t.subcategory_id = s.id AND t.is_active = TRUE AND t.term_type='search'
    WHERE c.is_active = TRUE
""")
print("\n=== VOCABULARY COUNTS ===")
print(json.dumps(count_terms[0] if count_terms else {}, indent=2, default=str))

# Per-category breakdown
per_cat = query(crm_conn, """
    SELECT c.category_code, count(t.phrase) AS term_count
    FROM crm_product_categories c
    JOIN crm_product_subcategories s ON s.category_id = c.id AND s.is_active = TRUE
    LEFT JOIN crm_product_subcategory_terms t ON t.subcategory_id = s.id AND t.is_active = TRUE AND t.term_type='search'
    WHERE c.is_active = TRUE
    GROUP BY c.category_code ORDER BY c.category_code
""")
print("\n=== TERMS PER CATEGORY ===")
for r in per_cat:
    print(f"  {r['category_code']}: {r['term_count']}")

crm_conn.close()

# Check document processor Git state
print("\n=== DOCUMENT PROCESSOR GIT STATE ===")
dp_root = "/opt/CRM_Streamlit/tender_documents_research"
result = subprocess.run(["git", "-C", dp_root, "log", "--oneline", "-3"], capture_output=True, text=True)
if result.returncode == 0:
    print("Git HEAD:", result.stdout.strip())
    branch = subprocess.run(["git", "-C", dp_root, "branch", "--show-current"], capture_output=True, text=True)
    print("Branch:", branch.stdout.strip())
else:
    print("Not a git repo:", result.stderr.strip())
    # Check for .git
    has_git = os.path.exists(os.path.join(dp_root, ".git"))
    print("Has .git dir:", has_git)
