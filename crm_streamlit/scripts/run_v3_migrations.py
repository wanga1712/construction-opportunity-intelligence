import sys
from src.services.db_bootstrap import connect_databases

def run_sql_file(crm_db, filepath):
    print(f"Applying migration: {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        sql = f.read()
    try:
        crm_db.execute_update(sql)
        print("Success.")
    except Exception as e:
        print(f"Error applying {filepath}: {e}")
        # If there's an error, raise it to abort the rest
        raise

def main():
    _, _, crm_db, _ = connect_databases()
    if not crm_db:
        print("Error: Could not connect to CRM database.")
        sys.exit(1)
        
    migrations = [
        "src/migrations/crm_v3_autonomous_learning_loop_1.sql",
        "src/migrations/crm_v3_autonomous_learning_loop_2.sql",
        "src/migrations/crm_v3_autonomous_learning_loop_3.sql",
        "src/migrations/crm_v3_routing_lease_retry_1.sql"
    ]
    
    for filepath in migrations:
        try:
            run_sql_file(crm_db, filepath)
        except Exception:
            sys.exit(1)
            
    print("All V3 migrations successfully applied!")

if __name__ == '__main__':
    main()
