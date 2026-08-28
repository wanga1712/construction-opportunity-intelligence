import sys
import psycopg2
from config.settings import Settings
from src.services.db_bootstrap import connect_databases

def main():
    config = Settings()
    host = getattr(config.crm_database, "host", "10.8.0.7")
    port = getattr(config.crm_database, "port", 5432)
    user = getattr(config.crm_database, "user", "postgres")
    # Retrieve password securely from settings
    pwd = config.crm_database.password if hasattr(config.crm_database, "password") else config._get_env_var("CRM_DB_PASSWORD", "")
    
    # 1. Connect to default 'postgres' to list databases
    try:
        conn = psycopg2.connect(host=host, port=port, user=user, password=pwd, database="postgres")
        with conn.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false")
            dbs = [r[0] for r in cur.fetchall()]
        conn.close()
        print("Available databases:", dbs)
    except Exception as e:
        print("Error listing databases:", e)
        dbs = ["crm", "tender_monitor", "radar_domrf", "document_intelligence"]

    # 2. Connect to each database and search for the traces table
    for db in dbs:
        try:
            conn = psycopg2.connect(host=host, port=port, user=user, password=pwd, database=db)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                      AND table_name = 'crm_v3_autonomous_analysis_traces'
                """)
                res = cur.fetchone()
                if res:
                    print(f"FOUND TABLE crm_v3_autonomous_analysis_traces in database: {db}!")
                else:
                    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
                    cnt = cur.fetchone()[0]
                    print(f"Database: {db} has {cnt} tables, but not crm_v3_autonomous_analysis_traces")
            conn.close()
        except Exception as e:
            print(f"Error checking database {db}: {e}")

if __name__ == '__main__':
    main()
