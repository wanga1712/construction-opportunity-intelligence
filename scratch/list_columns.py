import psycopg2

CRM_DB_URL = "host=127.0.0.1 port=5432 dbname=crm user=crm_app password=X17B3n5hbANQSRt6i7WIyy0lJudX"
DOC_DB_URL = "host=127.0.0.1 port=5432 dbname=document_intelligence user=doc_worker password=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT"

def list_cols(url, dbname):
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name, column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        ORDER BY table_name, ordinal_position
    """)
    rows = cur.fetchall()
    print(f"=== {dbname} Columns ===")
    tables = {}
    for r in rows:
        tables.setdefault(r[0], []).append(r[1])
    for t, cols in tables.items():
        print(f"  {t}: {cols}")
    conn.close()

print("Listing CRM cols:")
list_cols(CRM_DB_URL, "crm")
print("\nListing Doc Intel cols:")
list_cols(DOC_DB_URL, "document_intelligence")
