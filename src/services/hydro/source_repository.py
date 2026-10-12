"""Read-only NSPD source boundary."""
from __future__ import annotations

from typing import Any, Protocol

from .models import HydroSourceObject, source_row_to_object


class ReadOnlyQuery(Protocol):
    def query_all(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]: ...


SOURCE_SQL = """
SELECT co.id AS source_object_id, co.external_object_id, co.cadastral_number,
       co.name, co.purpose, co.object_type, co.address_text AS address,
       co.lat, co.lon, co.floors_underground, co.floors_total,
       co.construction_finish_year, co.commissioning_year, co.area_total,
       co.wall_material, pc.parking_type::text AS parking_type,
       pc.confidence_score, pc.candidate_reason, cm.status::text AS uk_status,
       cm.management_type, mc.id AS uk_id, mc.name AS uk_name,
       mc.inn AS uk_inn, mc.ogrn AS uk_ogrn, mc.phone AS uk_phone,
       co.updated_at AS source_updated_at
FROM cadastral_object co
JOIN parking_candidate pc ON pc.cadastral_object_id = co.id
LEFT JOIN cadastral_object_management cm ON cm.cadastral_object_id = co.id
LEFT JOIN management_company mc ON mc.id = cm.management_company_id
WHERE pc.is_parking_candidate = TRUE
"""


class NspdSourceRepository:
    def __init__(self, db: ReadOnlyQuery):
        self.db = db

    def fetch_objects(self) -> list[HydroSourceObject]:
        return [source_row_to_object(row) for row in self.db.query_all(SOURCE_SQL)]
