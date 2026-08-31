"""Политика приоритетов очереди обработки документов."""

from __future__ import annotations

from typing import List, Sequence


class QueuePriorityPolicy:
    """
    Высокий приоритет — новые реестры 44/223.
    Средний — разыгранные (awarded) 44/223.
    """

    HIGH_TABLES: Sequence[str] = (
        "reestr_contract_44_fz",
        "reestr_contract_223_fz",
    )
    MEDIUM_TABLES: Sequence[str] = (
        "reestr_contract_44_fz_awarded",
        "reestr_contract_223_fz_awarded",
    )

    def all_tables_ordered(self) -> List[str]:
        return list(self.HIGH_TABLES) + list(self.MEDIUM_TABLES)

    def high_tables(self) -> List[str]:
        return list(self.HIGH_TABLES)

    def is_high_priority(self, table_source: str) -> bool:
        return table_source in self.HIGH_TABLES

    def sql_order_case(self) -> str:
        """CASE для ORDER BY: 1 = высокий, 2 = средний, 3 = прочее."""
        high = ", ".join(f"'{t}'" for t in self.HIGH_TABLES)
        medium = ", ".join(f"'{t}'" for t in self.MEDIUM_TABLES)
        return f"""
                    CASE
                        WHEN table_source IN ({high}) THEN 1
                        WHEN table_source IN ({medium}) THEN 2
                        ELSE 3
                    END
        """.strip()
