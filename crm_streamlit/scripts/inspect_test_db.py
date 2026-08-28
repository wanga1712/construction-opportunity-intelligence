import sys
from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    if crm_db:
        try:
            cols = crm_db.execute_query("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'migration_history'")
            print("MIGRATION_HISTORY COLUMNS:")
            for c in cols:
                print(c)
            rows = crm_db.execute_query("SELECT * FROM migration_history LIMIT 10")
            print("MIGRATION_HISTORY ROWS:")
            for r in rows:
                print(r)
        except Exception as e:
            print("Error:", e)

if __name__ == '__main__':
    main()
