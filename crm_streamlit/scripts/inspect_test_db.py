from src.services.db_bootstrap import connect_databases

def main():
    _, _, crm_db, _ = connect_databases()
    if crm_db:
        res = crm_db.execute_query("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
              AND table_name = 'crm_v3_autonomous_analysis_traces'
        """)
        print("RESULT:", res)

if __name__ == '__main__':
    main()
