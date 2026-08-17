"""
Поиск контракта по номеру во всех реестрах (включая awarded).

Быстрый путь: end_date >= сегодня → только main + commission_work.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from utils.logger_config import get_logger

from database_work.contract_location import ContractLocation
from database_work.contract_lookup_strategy import (
    active_lookup_all_fz,
    active_lookup_tables,
    is_active_tender,
)
from database_work.database_connection import DatabaseManager
from database_work.registry_tables import all_lookup_tables, lookup_order, tables_for_fz

logger = get_logger()


class ContractRegistryLocator:
    """Ищет контракт по номеру в реестрах 44/223."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self._db = db_manager or DatabaseManager()

    def find_by_number(
        self,
        contract_number: str,
        end_date: Any = None,
        fz_type: Optional[str] = None,
    ) -> Optional[ContractLocation]:
        """
        Глобальный поиск по номеру.

        При end_date >= сегодня — только main/commission (2–4 запроса).
        Иначе — полный обход всех таблиц.
        """
        number = self._normalize_number(contract_number)
        if not number:
            return None

        if is_active_tender(end_date):
            if fz_type:
                return self._search_tables(number, active_lookup_tables(fz_type), fz_type)
            return self._search_pairs(number, active_lookup_all_fz())

        if fz_type:
            return self.find_in_fz(fz_type, number, end_date=None, force_full=True)

        return self._search_pairs(number, all_lookup_tables())

    def find_in_fz(
        self,
        fz_type: str,
        contract_number: str,
        end_date: Any = None,
        force_full: bool = False,
    ) -> Optional[ContractLocation]:
        """Поиск в контуре одного ФЗ."""
        number = self._normalize_number(contract_number)
        if not number:
            return None

        if not force_full and is_active_tender(end_date):
            return self._search_tables(number, active_lookup_tables(fz_type), fz_type)

        tables = tables_for_fz(fz_type)
        return self._search_tables(number, lookup_order(tables), fz_type)

    def find_in_fz_one_query(
        self, fz_type: str, contract_number: str
    ) -> Optional[ContractLocation]:
        """Preserve lifecycle lookup order using one DB round-trip."""
        number = self._normalize_number(contract_number)
        if not number:
            return None
        table_names = lookup_order(tables_for_fz(fz_type))
        branches = []
        params = []
        for priority, table_name in enumerate(table_names):
            branches.append(
                f"SELECT id, '{table_name}'::text AS table_name, "
                f"{priority} AS priority FROM {table_name} "
                "WHERE contract_number = %s LIMIT 1"
            )
            params.append(number)
        query = (
            "SELECT id, table_name FROM (" + " UNION ALL ".join(branches) +
            ") candidates ORDER BY priority LIMIT 1"
        )
        try:
            with self._db.connection.cursor() as cursor:
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
            if not row:
                return None
            return ContractLocation(
                fz_type=fz_type,
                table_name=str(row[1]),
                record_id=int(row[0]),
                contract_number=number,
            )
        except Exception as exc:
            logger.error(f"Ошибка unified lookup контракта {number}: {exc}")
            try:
                self._db.connection.rollback()
            except Exception:
                pass
            return None

    def _search_pairs(
        self,
        contract_number: str,
        pairs: List[Tuple[str, str]],
    ) -> Optional[ContractLocation]:
        for fz_type, table_name in pairs:
            record_id = self._fetch_id(table_name, contract_number)
            if record_id is not None:
                return ContractLocation(
                    fz_type=fz_type,
                    table_name=table_name,
                    record_id=record_id,
                    contract_number=contract_number,
                )
        return None

    def _search_tables(
        self,
        contract_number: str,
        table_names: List[str],
        fz_type: str,
    ) -> Optional[ContractLocation]:
        for table_name in table_names:
            record_id = self._fetch_id(table_name, contract_number)
            if record_id is not None:
                return ContractLocation(
                    fz_type=fz_type,
                    table_name=table_name,
                    record_id=record_id,
                    contract_number=contract_number,
                )
        return None

    @staticmethod
    def _normalize_number(contract_number: str) -> Optional[str]:
        if not contract_number:
            return None
        number = str(contract_number).strip()
        return number or None

    def _fetch_id(self, table_name: str, contract_number: str) -> Optional[int]:
        try:
            with self._db.connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT id FROM {table_name} WHERE contract_number = %s LIMIT 1",
                    (contract_number,),
                )
                row = cursor.fetchone()
                return int(row[0]) if row else None
        except Exception as exc:
            logger.error(
                f"Ошибка поиска контракта {contract_number} в {table_name}: {exc}"
            )
            try:
                self._db.connection.rollback()
            except Exception:
                pass
            return None
