"""
Поиск контракта по contract_number во всех слоях реестра.

Используется document_processor для resolve tender_id и загрузки links.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Sequence, Tuple

from .registry_tables import (
    canonical_priority_order,
    document_lookup_order,
    qualified,
    tables_for_source,
)


@dataclass(frozen=True)
class ContractHit:
    table_name: str
    tender_id: int


@dataclass(frozen=True)
class ContractLookupResult:
    contract_number: str
    fz_type: str
    canonical_table: Optional[str]
    canonical_id: Optional[int]
    confirmed_ids: FrozenSet[int]
    hits: Tuple[ContractHit, ...]
    id_mismatch: bool


class RegistryContractLocator:
    """Ищет контракт по номеру во всех поддерживаемых таблицах реестра."""

    def __init__(self, db, db_alias: str, logger=None):
        self.db = db
        self.db_alias = db_alias
        self.logger = logger

    def lookup(
        self,
        contract_number: str,
        table_source: str,
    ) -> ContractLookupResult:
        tables = tables_for_source(table_source)
        fz_type = tables.fz_type
        priority = canonical_priority_order(tables)
        search_tables = document_lookup_order(tables)

        hits: List[ContractHit] = []
        for table_name in search_tables:
            hit = self._fetch_one(contract_number, table_name)
            if hit is not None:
                hits.append(hit)

        confirmed_ids = frozenset(h.tender_id for h in hits)
        id_mismatch = len(confirmed_ids) > 1

        if id_mismatch and self.logger:
            by_table = ", ".join(f"{h.table_name}={h.tender_id}" for h in hits)
            self.logger.warning(
                f"contract_number={contract_number}: разные id в слоях реестра: {by_table}"
            )

        canonical_table: Optional[str] = None
        canonical_id: Optional[int] = None
        hits_by_table = {h.table_name: h for h in hits}
        for table_name in priority:
            hit = hits_by_table.get(table_name)
            if hit is not None:
                canonical_table = table_name
                canonical_id = hit.tender_id
                break

        return ContractLookupResult(
            contract_number=contract_number,
            fz_type=fz_type,
            canonical_table=canonical_table,
            canonical_id=canonical_id,
            confirmed_ids=confirmed_ids,
            hits=tuple(hits),
            id_mismatch=id_mismatch,
        )

    def resolve_tender_id(
        self,
        contract_number: str,
        table_source: str,
    ) -> Optional[int]:
        result = self.lookup(contract_number, table_source)
        return result.canonical_id

    def _fetch_one(
        self,
        contract_number: str,
        table_name: str,
    ) -> Optional[ContractHit]:
        sql = f"SELECT id FROM {qualified(table_name)} WHERE contract_number = %s LIMIT 1"
        try:
            rows = self.db.execute_query(
                self.db_alias,
                sql,
                (contract_number,),
                fetch=True,
            )
            if rows:
                return ContractHit(table_name=table_name, tender_id=int(rows[0][0]))
        except Exception as exc:
            if self.logger:
                self.logger.debug(
                    f"lookup {table_name} для {contract_number}: {exc}"
                )
        return None

    @staticmethod
    def format_hits_summary(hits: Sequence[ContractHit]) -> str:
        if not hits:
            return "—"
        return ", ".join(f"{h.table_name}({h.tender_id})" for h in hits)
