"""Transactional CRM persistence for the Hydro canonical snapshot."""
from __future__ import annotations
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable
from .models import HydroSourceObject
from .scoring import lead_readiness, object_potential

ELIGIBILITY = "UNDERGROUND_ONLY"

class HydroPersistenceRepository:
    """Writes only Hydro-owned facts and approved Hydro extension tables."""
    def __init__(self, connection): self.connection = connection

    def sync(self, objects: Iterable[HydroSourceObject], *, dry_run: bool = False) -> dict[str, int | str]:
        rows = list(objects); now = datetime.now(timezone.utc)
        counts: dict[str, int | str] = defaultdict(int)
        candidates: list[HydroSourceObject] = []
        for obj in rows:
            if obj.parking_type not in (None, "UNDERGROUND"):
                continue
            if obj.parking_type is None: counts["invalid_rows"] += 1; continue
            candidates.append(obj)
        counts["source_rows_total"] = len(rows); counts["lead_eligible_rows"] = len(candidates)
        if dry_run: return self._dry_run(candidates, counts)
        try:
            with self.connection:
                with self.connection.cursor() as cur:
                    company_ids: dict[str, int] = {}
                    object_ids: dict[str, int] = {}
                    for obj in candidates:
                        oid, status = self._upsert_object(cur, obj, now)
                        counts[status] += 1; object_ids[obj.identity_key] = oid
                        cid, cstatus = self._upsert_company(cur, obj)
                        if cid is not None:
                            company_ids[obj.company_key] = cid
                            counts[cstatus] += 1
                            cur.execute("INSERT INTO mc_parking_links (mc_id,parking_object_id) VALUES (%s,%s) ON CONFLICT (mc_id,parking_object_id) DO NOTHING RETURNING id", (cid, oid))
                            counts["mc_parking_links_created" if cur.fetchone() else "mc_parking_links_reused"] += 1
                    grouped: dict[str, list[HydroSourceObject]] = defaultdict(list)
                    for obj in candidates: grouped[obj.company_key or obj.identity_key].append(obj)
                    for key, group in grouped.items():
                        cid = company_ids.get(key)
                        lead_kind = "COMPANY_CONTOUR" if cid else "STANDALONE_OBJECT"
                        lead_key = f"hydro:company:{key}" if cid else f"hydro:object:{group[0].identity_key}"
                        lid, lstatus = self._upsert_lead(cur, lead_key, lead_kind, cid, group)
                        counts[lstatus] += 1
                        for obj in group:
                            cur.execute("""INSERT INTO crm_hydro_lead_objects (lead_id,parking_object_id,relation_method,relation_confidence,is_primary) VALUES (%s,%s,'SOURCE_ID',1,%s) ON CONFLICT (lead_id,parking_object_id) DO UPDATE SET is_primary=EXCLUDED.is_primary""", (lid, object_ids[obj.identity_key], obj.identity_key == group[0].identity_key))
                            counts["lead_object_links_created" if cur.rowcount == 1 else "lead_object_links_reused"] += 1
                    cur.execute("""INSERT INTO crm_hydro_source_health (source,last_attempt_at,last_success_at,status,rows_seen,rows_inserted,rows_updated,rows_unchanged,rows_invalid) VALUES ('NSPD_PARKING',%s,%s,'SUCCESS',%s,%s,%s,%s,%s) ON CONFLICT (source) DO UPDATE SET last_attempt_at=EXCLUDED.last_attempt_at,last_success_at=EXCLUDED.last_success_at,status=EXCLUDED.status,rows_seen=EXCLUDED.rows_seen,rows_inserted=EXCLUDED.rows_inserted,rows_updated=EXCLUDED.rows_updated,rows_unchanged=EXCLUDED.rows_unchanged,rows_invalid=EXCLUDED.rows_invalid""", (now, now, counts["source_rows_total"], counts["prefunnel_rows_inserted"], counts["prefunnel_rows_updated"], counts["prefunnel_rows_unchanged"], counts["invalid_rows"]))
            counts["source_health_status"] = "SUCCESS"
            return dict(counts)
        except Exception:
            self.connection.rollback()
            raise

    def _dry_run(self, objects, counts):
        cur = self.connection.cursor()
        try:
            for obj in objects:
                cur.execute("SELECT id,source_system,source_object_id FROM parking_prefunnel_objects WHERE (source_system=%s AND source_object_id=%s) OR cadastral_number=%s ORDER BY id", ("NSPD_PARKING", obj.source_object_id, obj.cadastral_number))
                found = cur.fetchall()
                counts["would_update_objects" if found else "would_insert_objects"] += 1
            counts["distinct_companies"] = len({o.company_key for o in objects if o.company_key})
            counts["resolved_company_relations"] = sum(1 for o in objects if o.company_key)
            return dict(counts)
        finally: cur.close()

    def _upsert_object(self, cur, obj, now):
        cur.execute("SELECT id,source_system,source_object_id,source_payload FROM parking_prefunnel_objects WHERE source_system=%s AND source_object_id=%s", ("NSPD_PARKING", obj.source_object_id))
        row = cur.fetchone()
        if not row: cur.execute("SELECT id,source_system,source_object_id,source_payload FROM parking_prefunnel_objects WHERE cadastral_number=%s", (obj.cadastral_number,)); row = cur.fetchone()
        if row and row[1] and row[1] != "NSPD_PARKING": raise ValueError(f"source/cadastral conflict for {obj.cadastral_number}")
        facts = (obj.external_object_id, obj.cadastral_number, obj.purpose, obj.object_type, obj.address, obj.lat, obj.lon, obj.floors_total, obj.construction_finish_year, obj.commissioning_year, obj.area_total, obj.wall_material, obj.parking_type, obj.parking_confidence, obj.parking_candidate_reason, obj.management_status, obj.management_type, obj.source_updated_at, obj.first_seen_at or now, now, now, json.dumps(obj.source_payload, default=str, ensure_ascii=False))
        columns = "source_external_object_id,cadastral_number,purpose,object_type,address,lat,lon,floors_total,construction_finish_year,commissioning_year,area_total,wall_material,parking_type,parking_confidence,parking_candidate_reason,management_status,management_type,source_updated_at,first_seen_at,last_seen_at,synced_at,source_payload"
        if row:
            if row[3] == obj.source_payload:
                cur.execute("UPDATE parking_prefunnel_objects SET last_seen_at=%s,synced_at=%s WHERE id=%s", (now, now, row[0]))
                return row[0], "prefunnel_rows_unchanged"
            cur.execute(f"UPDATE parking_prefunnel_objects SET source_system='NSPD_PARKING',source_object_id=%s,{','.join(f'{c}=%s' for c in columns.split(','))} WHERE id=%s", (obj.source_object_id, *facts, row[0]))
            return row[0], "prefunnel_rows_updated"
        cur.execute(f"INSERT INTO parking_prefunnel_objects (source_system,source_object_id,{columns}) VALUES ('NSPD_PARKING',%s,{','.join(['%s']*len(facts))}) RETURNING id", (obj.source_object_id, *facts))
        return cur.fetchone()[0], "prefunnel_rows_inserted"

    def _upsert_company(self, cur, obj):
        if not obj.management_company_inn or not obj.management_company_name: return None, "companies_unresolved"
        cur.execute("SELECT id,name,inn FROM management_companies WHERE inn=%s", (obj.management_company_inn,)); row = cur.fetchone()
        if row: return row[0], "management_companies_reused"
        cur.execute("INSERT INTO management_companies (name,inn,actual_address,lat,lon) VALUES (%s,%s,%s,%s,%s) RETURNING id", (obj.management_company_name,obj.management_company_inn,obj.address,obj.lat,obj.lon))
        return cur.fetchone()[0], "management_companies_created"

    def _upsert_lead(self, cur, key, kind, company_id, group):
        best = max((object_potential(o) for o in group), key=lambda x: x.score)
        facts = {"company_resolved": company_id is not None, "usable_phone": bool(group[0].management_company_phone), "next_action": False}
        readiness = lead_readiness(facts)
        title = group[0].management_company_name if company_id else (group[0].address or group[0].cadastral_number or key)
        cur.execute("SELECT id,disposition_status FROM crm_leads WHERE source_object_id=%s", (key,)); row = cur.fetchone()
        if row: lid = row[0]; status = "company_contour_leads_reused" if kind == "COMPANY_CONTOUR" else "standalone_leads_reused"
        else:
            cur.execute("INSERT INTO crm_leads (pipeline_id,inbox_stage_id,title,owner_id,source_object_id) VALUES ((SELECT id FROM crm_pipelines WHERE code='parkings' AND is_active=TRUE),(SELECT id FROM crm_lead_inbox_stages WHERE stage_key='new'),%s,NULL,%s) RETURNING id", (title[:500], key)); lid = cur.fetchone()[0]; status = "company_contour_leads_created" if kind == "COMPANY_CONTOUR" else "standalone_leads_created"
        cur.execute("""INSERT INTO crm_hydro_lead_extensions (lead_id,lead_kind,hydro_state,management_company_id,object_potential,lead_readiness) VALUES (%s,%s,'NEW',%s,%s::jsonb,%s::jsonb) ON CONFLICT (lead_id) DO UPDATE SET lead_kind=EXCLUDED.lead_kind,management_company_id=EXCLUDED.management_company_id,object_potential=EXCLUDED.object_potential,lead_readiness=EXCLUDED.lead_readiness,updated_at=NOW()""", (lid,kind,company_id,json.dumps(asdict(best)),json.dumps(asdict(readiness))))
        return lid, status
