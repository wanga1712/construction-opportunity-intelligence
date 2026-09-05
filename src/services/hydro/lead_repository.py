"""CRM-only repository for the Hydro lead-card read model."""
from __future__ import annotations
from typing import Any
from dataclasses import asdict
from .card_projection import HydroLeadCardDTO, lead_card
from .models import source_row_to_object
from .scoring import object_potential

_SCHEMA_CODES = {"42P01", "42703", "42883"}

def _schema_error(exc: Exception) -> bool:
    return getattr(exc, "pgcode", None) in _SCHEMA_CODES or any(token in str(exc).lower() for token in ("does not exist", "undefined table", "undefined column"))

class HydroLeadRepository:
    def __init__(self, crm_db: Any):
        self.db = crm_db
        self.schema_available = True
        self.last_schema_error: str | None = None

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try: return self.db.execute_query(sql, params) or []
        except Exception as exc:
            if _schema_error(exc): self.schema_available = False; self.last_schema_error = str(exc); return []
            raise

    def list_leads(self, filters: dict[str, Any] | None = None, sort: str = "work_queue", limit: int = 50, offset: int = 0) -> list[HydroLeadCardDTO]:
        filters = filters or {}; clauses = ["1=1"]; params: list[Any] = []
        for key, column in (("lead_kind", "e.lead_kind"), ("hydro_state", "e.hydro_state")):
            if filters.get(key): clauses.append(f"{column} = %s"); params.append(filters[key])
        if filters.get("company_resolved") is True: clauses.append("e.management_company_id IS NOT NULL")
        if filters.get("company_resolved") is False: clauses.append("e.management_company_id IS NULL")
        if filters.get("min_area") is not None: clauses.append("EXISTS (SELECT 1 FROM crm_hydro_lead_objects fx JOIN parking_prefunnel_objects fo ON fo.id=fx.parking_object_id WHERE fx.lead_id=l.id AND fo.area_total >= %s)"); params.append(filters["min_area"])
        if filters.get("min_floors_underground") is not None: clauses.append("EXISTS (SELECT 1 FROM crm_hydro_lead_objects ff JOIN parking_prefunnel_objects pf ON pf.id=ff.parking_object_id WHERE ff.lead_id=l.id AND pf.floors_underground >= %s)"); params.append(filters["min_floors_underground"])
        if filters.get("source_health"): clauses.append("h.status = %s"); params.append(filters["source_health"])
        if filters.get("potential_grade"): clauses.append("e.object_potential->>'grade' = %s"); params.append(filters["potential_grade"])
        if filters.get("readiness_grade"): clauses.append("e.lead_readiness->>'grade' = %s"); params.append(filters["readiness_grade"])
        if filters.get("text"): clauses.append("(coalesce(mc.name,'') || ' ' || coalesce(po.address,'') || ' ' || coalesce(po.cadastral_number,'') || ' ' || coalesce(mc.inn,'') || ' ' || coalesce(mc.ogrn,'')) ILIKE %s"); params.append(f"%{filters['text']}%")
        order = "(e.hydro_state='MERGED') ASC, COALESCE((e.object_potential->>'score')::int,0) DESC, COALESCE((e.lead_readiness->>'score')::int,0) ASC, l.id ASC"
        if sort == "potential": order = "COALESCE((e.object_potential->>'score')::int,0) DESC, l.id ASC"
        sql = f"""SELECT l.id AS lead_id,e.lead_kind,e.hydro_state AS state,e.merged_into_lead_id,e.object_potential,e.lead_readiness,mc.name AS company_name,mc.inn AS company_inn,mc.ogrn AS company_ogrn,mc.phone AS company_phone,count(lo.parking_object_id)::int AS object_count,h.status AS source_health,h.last_success_at AS source_last_success_at FROM crm_leads l JOIN crm_hydro_lead_extensions e ON e.lead_id=l.id LEFT JOIN management_companies mc ON mc.id=e.management_company_id LEFT JOIN crm_hydro_lead_objects lo ON lo.lead_id=l.id LEFT JOIN parking_prefunnel_objects po ON po.id=lo.parking_object_id LEFT JOIN crm_hydro_source_health h ON h.source='NSPD_PARKING' WHERE {' AND '.join(clauses)} GROUP BY l.id,e.lead_kind,e.hydro_state,e.merged_into_lead_id,e.object_potential,e.lead_readiness,mc.name,mc.inn,mc.ogrn,mc.phone,h.status,h.last_success_at ORDER BY {order} LIMIT %s OFFSET %s"""
        rows = self._query(sql, tuple(params + [max(1, min(limit, 200)), max(0, offset)]))
        if not rows: return []
        ids = [row["lead_id"] for row in rows]
        placeholders = ",".join(["%s"] * len(ids))
        objects = self._query(f"SELECT lo.lead_id,po.id AS object_id,po.source_object_id,po.cadastral_number,po.address,po.area_total,po.floors_underground,po.parking_type,po.lat,po.lon FROM crm_hydro_lead_objects lo JOIN parking_prefunnel_objects po ON po.id=lo.parking_object_id WHERE lo.lead_id IN ({placeholders}) ORDER BY lo.lead_id,lo.is_primary DESC,po.id", tuple(ids))
        grouped: dict[Any, list[dict[str, Any]]] = {key: [] for key in ids}
        for obj in objects:
            try:
                source = source_row_to_object(obj)
                obj["object_potential"] = asdict(object_potential(source))
            except (TypeError, ValueError):
                obj["object_potential"] = None
            grouped.setdefault(obj["lead_id"], []).append(obj)
        return [lead_card(row, grouped.get(row["lead_id"], [])) for row in rows]

    def get_lead_objects(self, lead_id: int | str) -> list[dict[str, Any]]:
        rows = self._query("SELECT po.id AS object_id,po.source_object_id,po.cadastral_number,po.address,po.area_total,po.floors_underground,po.parking_type,po.lat,po.lon FROM crm_hydro_lead_objects lo JOIN parking_prefunnel_objects po ON po.id=lo.parking_object_id WHERE lo.lead_id=%s ORDER BY lo.is_primary DESC,po.id", (lead_id,))
        for row in rows:
            try: row["object_potential"] = asdict(object_potential(source_row_to_object(row)))
            except (TypeError, ValueError): pass
        return rows

    def get_lead(self, lead_id: int | str) -> HydroLeadCardDTO | None:
        rows = self._query("SELECT l.id AS lead_id,e.lead_kind,e.hydro_state AS state,e.merged_into_lead_id,e.object_potential,e.lead_readiness,mc.name AS company_name,mc.inn AS company_inn,mc.ogrn AS company_ogrn,mc.phone AS company_phone,h.status AS source_health,h.last_success_at AS source_last_success_at FROM crm_leads l JOIN crm_hydro_lead_extensions e ON e.lead_id=l.id LEFT JOIN management_companies mc ON mc.id=e.management_company_id LEFT JOIN crm_hydro_source_health h ON h.source='NSPD_PARKING' WHERE l.id=%s", (lead_id,))
        return lead_card(rows[0], self.get_lead_objects(lead_id)) if rows else None

    def get_source_health(self) -> list[dict[str, Any]]: return self._query("SELECT source,status,last_attempt_at,last_success_at,rows_seen,safe_error_class FROM crm_hydro_source_health ORDER BY source")
    def get_counts_by_lead_kind(self) -> dict[str, int]: return {str(r['lead_kind']): int(r['count']) for r in self._query("SELECT lead_kind,count(*)::int AS count FROM crm_hydro_lead_extensions GROUP BY lead_kind")}
    def get_counts_by_state(self) -> dict[str, int]: return {str(r['hydro_state']): int(r['count']) for r in self._query("SELECT hydro_state,count(*)::int AS count FROM crm_hydro_lead_extensions GROUP BY hydro_state")}
