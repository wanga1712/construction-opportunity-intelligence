import sys
import re
from src.services.db_bootstrap import connect_databases

def run_sql_file(crm_db, filepath):
    print(f"Applying migration: {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        sql = f.read()
    
    # Simple split by semicolon (avoiding comments and quotes splits when possible)
    # We clean up SQL comments first
    sql_clean = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    statements = sql_clean.split(';')
    
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            crm_db.execute_update(stmt)
        except Exception as e:
            err_msg = str(e)
            if "role \"crm_app\" does not exist" in err_msg or "crm_app" in err_msg:
                print(f"Skipping statement due to missing crm_app role: {stmt[:60]}...")
            else:
                print(f"Error applying statement:\n{stmt}\nError: {e}")
                raise
    print("Success.")

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
