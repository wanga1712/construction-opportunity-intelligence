"""
Подключение к тем же БД, что и десктопное CRM-приложение.
"""
from typing import Optional, Tuple

from loguru import logger

from config.settings import Settings
from core.radar_database import RadarDatabaseManager
from core.tender_database import TenderDatabaseManager
from modules.crm.crm_database import CrmDatabaseManager


def connect_databases() -> Tuple[
    Optional[RadarDatabaseManager],
    Optional[TenderDatabaseManager],
    Optional[CrmDatabaseManager],
    str,
]:
    """
    Подключить Radar, Tender и CRM.

    Returns:
        (radar_db, tender_db, crm_db, warning_message)
    """
    errors = []
    config = Settings()
    db_hosts = {
        "Radar": getattr(getattr(config, "radar_database", None), "host", None)
        or config._get_env_var("DOM_RF_RADAR_DB_HOST", "?"),
        "Tender": getattr(getattr(config, "tender_database", None), "host", None)
        or config._get_env_var("TENDER_MONITOR_DB_HOST", "?"),
        "CRM": getattr(getattr(config, "crm_database", None), "host", None)
        or config._get_env_var("CRM_DB_HOST", "?"),
    }

    radar_db: Optional[RadarDatabaseManager] = None
    tender_db: Optional[TenderDatabaseManager] = None
    crm_db: Optional[CrmDatabaseManager] = None

    try:
        radar_db = RadarDatabaseManager(config.radar_database)
        radar_db.connect()
    except Exception as e:
        logger.error(f"Radar DB: {e}")
        errors.append(f"Radar: {e}")

    try:
        tender_db = TenderDatabaseManager(config.tender_database)
        tender_db.connect()
    except Exception as e:
        logger.warning(f"Tender DB: {e}")
        errors.append(f"Tender: {e}")

    try:
        crm_db = CrmDatabaseManager(config.crm_database)
        crm_db.connect()
    except Exception as e:
        logger.warning(f"CRM DB: {e}")
        errors.append(f"CRM: {e}")

    if not radar_db:
        hosts_hint = ", ".join(f"{k}={v}" for k, v in db_hosts.items())
        return (
            None,
            tender_db,
            crm_db,
            f"База Radar недоступна ({hosts_hint}). "
            "Проверьте .env, VPN и pg_hba на PostgreSQL (хост 10.8.0.7).",
        )

    warn = "; ".join(errors) if errors else ""
    return radar_db, tender_db, crm_db, warn
