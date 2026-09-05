"""Canonical CRM read model for Hydro commercial hierarchy."""
from __future__ import annotations

from typing import Any

from .commercial_hierarchy import CommercialEntity, build_commercial_entities


class HydroCommercialRepository:
    """Read canonical Hydro facts without source calls or fact mutation."""

    def __init__(self, crm_db: Any):
        self.db = crm_db
        self.schema_available = True
        self.last_error: str | None = None

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            return self.db.execute_query(sql, params) or []
        except Exception as exc:
            self.schema_available = False
            self.last_error = str(exc)
            return []

    def list_entities(self, *, limit: int = 7000) -> tuple[CommercialEntity, ...]:
        rows = self._query(
            """
            SELECT DISTINCT ON (po.id)
                po.id AS object_id, po.source_object_id, po.cadastral_number,
                po.address, po.area_total, po.floors_underground,
                po.floors_total, po.purpose, po.object_type,
                po.construction_finish_year, po.commissioning_year,
                po.parking_type, po.management_status, po.management_type,
                po.source_payload->>'name' AS name,
                po.source_payload->>'uk_id' AS source_company_id,
                po.source_payload->>'uk_ogrn' AS company_ogrn,
                (nullif(po.source_payload->>'uk_phone', '') IS NOT NULL) AS company_phone_exists,
                e.management_company_id, mc.name AS company_name, mc.inn AS company_inn,
                e.object_potential, e.lead_readiness, e.lead_id
            FROM parking_prefunnel_objects po
            LEFT JOIN crm_hydro_lead_objects lo ON lo.parking_object_id=po.id
            LEFT JOIN crm_hydro_lead_extensions e ON e.lead_id=lo.lead_id
            LEFT JOIN management_companies mc ON mc.id=e.management_company_id
            WHERE po.source_system='NSPD_PARKING'
            ORDER BY po.id, lo.is_primary DESC NULLS LAST, lo.lead_id
            LIMIT %s
            """,
            (max(1, min(limit, 10000)),),
        )
        return build_commercial_entities(rows)

    def counts(self) -> dict[str, int]:
        entities = self.list_entities()
        counts = {"ZHILISHNIK": 0, "OTHER_UK": 0, "NO_UK_KNOWN": 0, "UNKNOWN": 0}
        for entity in entities:
            counts[entity.layer.value] += 1
        return counts
