import sys
from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    if crm_db:
        try:
            history = crm_db.execute_query("SELECT version, description, applied_at FROM migration_history ORDER BY id ASC")
            print("MIGRATION HISTORY:")
            for h in history:
                print(h)
        except Exception as e:
            print("Error querying migration_history:", e)

if __name__ == '__main__':
    main()
