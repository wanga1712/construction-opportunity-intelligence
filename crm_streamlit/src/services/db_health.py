"""Проверка и переподключение БД для Streamlit CRM."""
from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.services.companies_service import CompaniesService


@dataclass
class DbHealthResult:
    radar_ok: bool
    crm_ok: bool
    reconnected: bool = False

    @property
    def all_required_ok(self) -> bool:
        return self.radar_ok


def _ensure_manager(db: Any, label: str) -> bool:
    if db is None:
        return True
    try:
        if db.is_connected():
            return True
        if hasattr(db, "reconnect"):
            ok = db.reconnect()
            if ok:
                logger.info(f"{label}: переподключение успешно")
            return ok
        return False
    except Exception as e:
        logger.warning(f"{label}: проверка соединения — {e}")
        return False


def check_and_reconnect(
    service: CompaniesService, *, previously_online: bool = True,
) -> DbHealthResult:
    """Ping + reconnect для Radar и CRM."""
    radar_ok = _ensure_manager(service.radar_db, "Radar")
    crm_db = service.profile_repo.db if service.profile_repo else None
    crm_ok = _ensure_manager(crm_db, "CRM")

    reconnected = (not previously_online) and radar_ok
    return DbHealthResult(radar_ok=radar_ok, crm_ok=crm_ok, reconnected=reconnected)


def check_databases(service: CompaniesService) -> DbHealthResult:
    """Compatibility alias for ping + reconnect of Radar/CRM databases."""
    return check_and_reconnect(service)
