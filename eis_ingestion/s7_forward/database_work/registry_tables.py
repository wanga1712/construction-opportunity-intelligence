"""
Карта таблиц реестра контрактов 44/223.

Комментарии на русском. Без бизнес-логики — только имена и порядок поиска.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


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


def lookup_order(tables: RegistryTables) -> List[str]:
    """
    Порядок поиска контракта по номеру.

    main → unknown → unclear → awarded.
    completed не ищем и не обновляем — только статистика.
    commission_work — между main и unknown (живой статус до миграции).
    """
    ordered: List[str] = [
        tables.main,
        tables.commission_work,
    ]
    if tables.unknown:
        ordered.append(tables.unknown)
    ordered.append(tables.unclear)
    ordered.append(tables.awarded)
    return ordered


def tables_for_fz(fz_type: str) -> RegistryTables:
    """Возвращает карту таблиц для '44' или '223'."""
    if fz_type == "44":
        return TABLES_44
    if fz_type == "223":
        return TABLES_223
    raise ValueError(f"Неизвестный тип ФЗ: {fz_type}")


def all_lookup_tables() -> List[Tuple[str, str]]:
    """
    Плоский список (fz_type, table_name) для глобального поиска номера.
    Порядок внутри ФЗ: main → commission → unknown → unclear → awarded.
    """
    result: List[Tuple[str, str]] = []
    for tables in (TABLES_44, TABLES_223):
        for name in lookup_order(tables):
            result.append((tables.fz_type, name))
    return result


# Поля, которые разрешено обновлять из RGK/recouped XML.
ALLOWED_UPDATE_FIELDS = (
    "contractor_id",
    "delivery_start_date",
    "delivery_end_date",
    "final_price",
    "initial_price",
    "guarantee_amount",
    "okpd_id",
    "auction_name",
    "region_id",
)

# Canonical registry columns accepted from parser output on INSERT.  Parser
# helper/provenance keys must be mapped before this boundary, never promoted
# to SQL identifiers by dict expansion.
COMMON_INSERT_FIELDS = frozenset(
    {
        "contract_number", "tender_link", "start_date", "end_date",
        "delivery_start_date", "delivery_end_date", "auction_name",
        "initial_price", "final_price", "guarantee_amount", "customer_id",
        "contractor_id", "trading_platform_id", "okpd_id",
        "delivery_region", "delivery_address", "region_id", "status_id",
    }
)

INSERT_FIELDS_BY_FZ = {
    "44": COMMON_INSERT_FIELDS | {"customer", "warranty_size"},
    "223": COMMON_INSERT_FIELDS | {"placer", "placer_inn"},
}


def persistence_payload(fz_type: str, parser_fields: dict) -> dict:
    """Map parser output to the explicit canonical registry INSERT contract."""
    allowed = INSERT_FIELDS_BY_FZ[fz_type]
    return {key: value for key, value in parser_fields.items() if key in allowed}
