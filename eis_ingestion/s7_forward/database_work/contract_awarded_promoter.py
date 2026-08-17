"""
Перенос контракта в разыгранные после появления подрядчика и дат.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger_config import get_logger

from database_work.contract_location import ContractLocation
from database_work.database_connection import DatabaseManager
from database_work.registry_tables import tables_for_fz

logger = get_logger()


class ContractAwardedPromoter:
    """
    Переводит контракт в *_awarded, если выполнены условия.

    Условие (сценарий unknown/unclear → awarded):
    - есть contractor_id
    - есть delivery_end_date (дата окончания поставки)
    Уже awarded / completed не трогаем (только UPDATE снаружи).
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self._db = db_manager or DatabaseManager()

    def should_promote(
        self, location: ContractLocation, fields: Dict[str, Any]
    ) -> bool:
        if location.is_awarded:
            return False
        if location.table_name.endswith("_completed"):
            return False
        if not location.is_promotable_source:
            return False

        # For 223-FZ this method is called only from the authoritative
        # contractCutted sync path. A linked concluded contract is sufficient
        # for AWARDED even when optional supplier/execution fields are absent.
        if location.fz_type == "223":
            return True

        # 44-FZ keeps its existing, stricter awarded requirements unchanged.
        contractor_id = fields.get("contractor_id")
        delivery_end = fields.get("delivery_end_date")
        return contractor_id is not None and delivery_end is not None

    def promote(self, location: ContractLocation) -> Optional[ContractLocation]:
        """
        INSERT INTO awarded SELECT * FROM source; DELETE FROM source.
        Сохраняет тот же id.
        """
        tables = tables_for_fz(location.fz_type)
        awarded = tables.awarded
        source = location.table_name
        if source == awarded:
            return location

        try:
            with self._db.connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT 1 FROM {awarded} WHERE id = %s LIMIT 1",
                    (location.record_id,),
                )
                already = cursor.fetchone() is not None

                if not already:
                    cursor.execute(
                        f"""
                        INSERT INTO {awarded}
                        SELECT * FROM {source}
                        WHERE id = %s
                        """,
                        (location.record_id,),
                    )
                    if cursor.rowcount < 1:
                        self._db.connection.rollback()
                        logger.error(
                            f"Не удалось вставить в {awarded} id={location.record_id}"
                        )
                        return None

                # Обходим FK при удалении из исходной таблицы
                cursor.execute("SET session_replication_role = 'replica'")
                cursor.execute(
                    f"DELETE FROM {source} WHERE id = %s",
                    (location.record_id,),
                )
                cursor.execute("SET session_replication_role = 'origin'")
                self._db.connection.commit()

                logger.debug(
                    f"Контракт {location.contract_number} перенесён "
                    f"{source} → {awarded} (id={location.record_id})"
                )
                return ContractLocation(
                    fz_type=location.fz_type,
                    table_name=awarded,
                    record_id=location.record_id,
                    contract_number=location.contract_number,
                )
        except Exception as exc:
            logger.error(
                f"Ошибка promote {location.contract_number} "
                f"{source}→{awarded}: {exc}"
            )
            try:
                self._db.connection.rollback()
                with self._db.connection.cursor() as cursor:
                    cursor.execute("SET session_replication_role = 'origin'")
            except Exception:
                pass
            return None
