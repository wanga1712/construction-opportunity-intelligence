"""
Карта таблиц реестра контрактов 44/223 для document_processor.

Только имена и порядок — без бизнес-логики.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


SCHEMA = "public"


@dataclass(frozen=True)
class RegistryTables:
    """Имена таблиц одного контура ФЗ."""

    fz_type: str
    main: str
    commission_work: str
    unclear: str
    awarded: str
    completed: Optional[str] = None
    unknown: Optional[str] = None


TABLES_44 = RegistryTables(
    fz_type="44",
    main="reestr_contract_44_fz",
    commission_work="reestr_contract_44_fz_commission_work",
    unclear="reestr_contract_44_fz_unclear",
    awarded="reestr_contract_44_fz_awarded",
    completed="reestr_contract_44_fz_completed",
    unknown="reestr_contract_44_fz_unknown",
)

TABLES_223 = RegistryTables(
    fz_type="223",
    main="reestr_contract_223_fz",
    commission_work="reestr_contract_223_fz_commission_work",
    unclear="reestr_contract_223_fz_unclear",
    awarded="reestr_contract_223_fz_awarded",
    completed="reestr_contract_223_fz_completed",
    unknown=None,
)


def qualified(table: str, schema: str = SCHEMA) -> str:
    """Возвращает schema-qualified имя таблицы."""
    if "." in table:
        return table
    return f"{schema}.{table}"


def fz_type_from_table_source(table_source: str) -> str:
    """Определяет контур ФЗ по имени table_source из очереди."""
    if "223" in table_source:
        return "223"
    return "44"


def tables_for_fz(fz_type: str) -> RegistryTables:
    if fz_type == "44":
        return TABLES_44
    if fz_type == "223":
        return TABLES_223
    raise ValueError(f"Неизвестный тип ФЗ: {fz_type}")


def tables_for_source(table_source: str) -> RegistryTables:
    return tables_for_fz(fz_type_from_table_source(table_source))


def canonical_priority_order(tables: RegistryTables) -> List[str]:
    """
    Приоритет выбора канонической записи (от более «актуального» слоя к менее).

    awarded → completed → main → commission_work → unclear → unknown.
    """
    ordered: List[str] = [
        tables.awarded,
        tables.completed or "",
        tables.main,
        tables.commission_work,
        tables.unclear,
    ]
    if tables.unknown:
        ordered.append(tables.unknown)
    return [name for name in ordered if name]


def document_lookup_order(tables: RegistryTables) -> List[str]:
    """Все слои реестра для поиска contract_number и links (включая completed)."""
    return canonical_priority_order(tables)


def links_table_for_source(table_source: str) -> str:
    if "223" in table_source:
        return "links_documentation_223_fz"
    return "links_documentation_44_fz"
