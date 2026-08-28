import sys
from config.settings import Settings
from src.services.db_bootstrap import connect_databases

def main():
    config = Settings()
    print("CRM DB Config:")
    print("Host:", getattr(config.crm_database, "host", None))
    print("Port:", getattr(config.crm_database, "port", None))
    print("Database:", getattr(config.crm_database, "database", None))
    print("User:", getattr(config.crm_database, "user", None))
    
    # Check if tables exist in doc_conn as well
    _, t, c, _ = connect_databases()
    if t:
        print("Tender DB tables:")
        try:
            tables = t.execute_query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            for tbl in tables[:15]:
                print(tbl)
        except Exception as e:
            print("Error Tender tables:", e)

if __name__ == '__main__':
    main()
