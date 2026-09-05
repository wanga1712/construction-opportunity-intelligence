import psycopg2

conn = psycopg2.connect('dbname=crm')
cur = conn.cursor()

for table in ['links_documentation_contract', 'links_documentation_contract_223', 'links_documentation_purchase', 'links_documentation_purchase_223']:
    try:
        cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'")
        print(f"Table {table}:")
        for r in cur.fetchall():
            print(f"  {r[0]}: {r[1]}")
    except Exception as e:
        print(f"Error {table}: {e}")

conn.close()
