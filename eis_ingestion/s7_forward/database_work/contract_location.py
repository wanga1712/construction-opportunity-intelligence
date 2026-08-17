"""
Модель расположения контракта в реестре.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractLocation:
    """Где лежит контракт в БД."""

    fz_type: str
    table_name: str
    record_id: int
    contract_number: str

    @property
    def is_awarded(self) -> bool:
        return self.table_name.endswith("_awarded")

    @property
    def is_promotable_source(self) -> bool:
        """Можно ли переносить в разыгранные из этой таблицы."""
        if self.table_name.endswith("_completed"):
            return False
        suffixes = ("_unknown", "_unclear", "_commission_work")
        # основная таблица тоже — если доехали подрядчик и даты
        if self.table_name in (
            "reestr_contract_44_fz",
            "reestr_contract_223_fz",
        ):
            return True
        return any(self.table_name.endswith(s) for s in suffixes)
