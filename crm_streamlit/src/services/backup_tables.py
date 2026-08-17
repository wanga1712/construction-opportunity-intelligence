"""Скрипт резервного копирования затрагиваемых таблиц перед миграцией."""
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, "/opt/CRM_Streamlit")
sys.path.insert(0, "/opt/pythonProject89")

from dotenv import load_dotenv
load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.db_bootstrap import connect_databases

def backup():
    _radar, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning(f"Connection warning: {warn}")

    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. Бэкап в tender_monitor (сервер 7)
    conn_t = tender_db.get_connection()
    tables_t = ["okpd_route_profiles", "procurement_ai_assessments", "cohort_medians", "queue_policy_shadow_runs", "queue_policy_shadow_results"]
    logger.info("Backing up tables in 'tender_monitor'...")
    with conn_t:
        with conn_t.cursor() as cur:
            for tbl in tables_t:
                # Проверим существование таблицы
                cur.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{tbl}')")
                row = cur.fetchone()
                exists = list(row.values())[0] if isinstance(row, dict) else (row[0] if row else False)
                if exists:
                    backup_name = f"backup_{suffix}_{tbl}"
                    logger.info(f"Copying {tbl} -> {backup_name}...")
                    cur.execute(f"CREATE TABLE {backup_name} AS SELECT * FROM {tbl}")
                else:
                    logger.info(f"Table {tbl} does not exist. Skipping backup.")

    # 2. Бэкап в crm (сервер 13)
    conn_c = crm_db._connection
    tables_c = ["crm_procurements", "okpd_route_profiles", "procurement_ai_assessments"]
    logger.info("Backing up tables in 'crm'...")
    if conn_c:
        with conn_c:
            with conn_c.cursor() as cur:
                for tbl in tables_c:
                    cur.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{tbl}')")
                    row = cur.fetchone()
                    exists = list(row.values())[0] if isinstance(row, dict) else (row[0] if row else False)
                    if exists:
                        backup_name = f"backup_{suffix}_{tbl}"
                        logger.info(f"Copying {tbl} -> {backup_name}...")
                        cur.execute(f"CREATE TABLE {backup_name} AS SELECT * FROM {tbl}")
                    else:
                        logger.info(f"Table {tbl} does not exist. Skipping backup.")
    else:
        logger.error("CRM database raw connection is unavailable")

if __name__ == "__main__":
    backup()
