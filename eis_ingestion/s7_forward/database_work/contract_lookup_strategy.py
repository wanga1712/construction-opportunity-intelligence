"""
Стратегия поиска контракта: быстрый путь для активных закупок.

end_date >= сегодня → только main + commission_work (ещё без миграций).
Иначе → полный обход всех реестров.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from database_work.registry_tables import RegistryTables, tables_for_fz


def parse_end_date(value: Any) -> Optional[date]:
    """Приводит end_date из XML/БД к date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_active_tender(end_date: Any) -> bool:
    """
    Активная закупка: end_date есть и не раньше сегодняшнего дня.
    Без end_date — не угадываем, нужен полный поиск.
    """
    parsed = parse_end_date(end_date)
    if parsed is None:
        return False
    return parsed >= date.today()


def active_lookup_tables(fz_type: str) -> List[str]:
    """main + commission_work для одного контура ФЗ."""
    tables: RegistryTables = tables_for_fz(fz_type)
    return [tables.main, tables.commission_work]


def active_lookup_all_fz() -> List[tuple[str, str]]:
    """main + commission для 44 и 223 (глобальный быстрый поиск)."""
    result: List[tuple[str, str]] = []
    for fz in ("44", "223"):
        for table_name in active_lookup_tables(fz):
            result.append((fz, table_name))
    return result
