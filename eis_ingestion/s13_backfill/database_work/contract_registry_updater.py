"""
Обновление полей контракта в найденной таблице реестра.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger_config import get_logger

from database_work.contract_location import ContractLocation
from database_work.database_connection import DatabaseManager
from database_work.registry_tables import ALLOWED_UPDATE_FIELDS

logger = get_logger()


class ContractRegistryUpdater:
    """Пишет разрешённые поля в ту таблицу, где лежит контракт."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self._db = db_manager or DatabaseManager()

    def update(self, location: ContractLocation, fields: Dict[str, Any]) -> bool:
        """
        Обновляет только непустые разрешённые поля.

        awarded обновляем (ссылки/даты/подрядчик могут доезжать).
        completed — никогда (только статистика).
        """
        if location.table_name.endswith("_completed"):
            logger.info(
                f"Пропуск UPDATE для completed: {location.contract_number} "
                f"({location.table_name})"
            )
            return False

        payload = {
            key: value
            for key, value in fields.items()
            if key in ALLOWED_UPDATE_FIELDS and value is not None
        }
        if not payload:
            return True

        columns = []
        values = []
        for key, value in payload.items():
            columns.append(f"{key} = %s")
            values.append(value)
        values.append(location.record_id)

        columns.append("updated_at = NOW()")
        query = f"""
            UPDATE {location.table_name}
            SET {', '.join(columns)}
            WHERE id = %s
        """
        try:
            with self._db.connection.cursor() as cursor:
                cursor.execute(query, tuple(values))
                self._db.connection.commit()
                logger.info(
                    f"Обновлён контракт {location.contract_number} "
                    f"в {location.table_name} (id={location.record_id}), "
                    f"поля={list(payload.keys())}"
                )
                return True
        except Exception as exc:
            logger.error(
                f"Ошибка UPDATE {location.table_name} id={location.record_id}: {exc}"
            )
            try:
                self._db.connection.rollback()
            except Exception:
                pass
            return False
