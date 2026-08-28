import sys
from src.services.db_bootstrap import connect_databases

def main():
    radar_db, tender_db, crm_db, warning = connect_databases()
    print("WARNING:", warning)
    if crm_db:
        print("CRM_DB object:", crm_db)
        try:
            print("SEARCH_PATH:", crm_db.execute_query("SHOW search_path"))
        except Exception as e:
            print("Error SHOW search_path:", e)
        try:
            tables = crm_db.execute_query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            print("Public tables:")
            for t in tables:
                print(t)
        except Exception as e:
            print("Error listing tables:", e)
            
        try:
            schemas = crm_db.execute_query("SELECT schema_name FROM information_schema.schemata")
            print("Schemas:")
            for s in schemas:
                print(s)
        except Exception as e:
            print("Error listing schemas:", e)

if __name__ == '__main__':
    main()
