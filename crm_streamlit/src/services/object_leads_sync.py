"""Batch synchronization of eligible awarded object leads."""
from __future__ import annotations

from loguru import logger

from src.services.object_lifecycle import DEFAULT_SALES_WINDOW_DAYS

AWARDED_MIN_DAYS_LEFT = DEFAULT_SALES_WINDOW_DAYS


def sync_awarded_object_leads(crm_db, items, *, min_days_left: int = AWARDED_MIN_DAYS_LEFT) -> dict:
    """Create persistent lead state for awarded tenders still in the sales window."""
    stats = {"scanned": 0, "eligible": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0}
    if not crm_db or crm_db.is_offline_mode():
        stats["error"] = "CRM DB unavailable"
        return stats
    try:
        rows = crm_db.execute_query(
            """
            WITH params AS (
                SELECT (CURRENT_DATE + (%s::int * INTERVAL '1 day'))::date AS min_end_date,
                  (SELECT id FROM crm_pipelines WHERE code='procurement_44fz' AND is_active=TRUE LIMIT 1) AS p44,
                  (SELECT id FROM crm_pipelines WHERE code='procurement_223fz' AND is_active=TRUE LIMIT 1) AS p223,
                  (SELECT id FROM crm_lead_inbox_stages WHERE stage_key='reviewed' LIMIT 1) AS reviewed_stage
            ), source AS (
                SELECT oi.*, CASE WHEN COALESCE(oi.registry_type, '') ILIKE '%%223%%'
                    THEN COALESCE((SELECT p223 FROM params), 9) ELSE COALESCE((SELECT p44 FROM params), 8) END AS pipeline_id,
                  COALESCE((SELECT reviewed_stage FROM params), 2) AS inbox_stage_id,
                  LEAST(100, LEAST(35, COALESCE(oi.doc_matches, 0)) + LEAST(20, COALESCE(oi.matched_files, 0) * 3)
                    + CASE WHEN oi.expertise_number IS NOT NULL THEN 15 ELSE 0 END
                    + CASE WHEN oi.customer_inn IS NOT NULL OR oi.contractor_inn IS NOT NULL THEN 10 ELSE 0 END) AS lead_score
                FROM crm_objects_index oi, params p
                WHERE COALESCE(oi.registry_type, '') ILIKE '%%awarded%%'
                  AND COALESCE(oi.delivery_end_date, oi.end_date) >= p.min_end_date
            ), upsert_ext AS (
                INSERT INTO crm_external_entities (source_type, source_key, payload, updated_at)
                SELECT 'tender_object', object_key, jsonb_build_object(
                  'object_key',object_key,'registry_type',registry_type,'tender_id',tender_id,'name',name,'address',address,
                  'region',region_name,'region_id',region_id,'status',status,'contract_number',contract_number,
                  'expertise_number',expertise_number,'doc_matches',doc_matches,'matched_files',matched_files,
                  'delivery_start_date',delivery_start_date,'delivery_end_date',delivery_end_date,'end_date',end_date,
                  'customer_name',customer_name,'customer_inn',customer_inn,'contractor_name',contractor_name,
                  'contractor_inn',contractor_inn,'balance_holder',balance_holder,'segment',segment,'source','crm_objects_index'), NOW()
                FROM source ON CONFLICT (source_type, source_key)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW() RETURNING source_key, id
            ), ext AS (
                SELECT source_key, id FROM upsert_ext UNION SELECT source_key, id FROM crm_external_entities
                WHERE source_type='tender_object' AND source_key IN (SELECT object_key FROM source)
            ), updated AS (
                UPDATE crm_leads l SET external_entity_id=ext.id,pipeline_id=s.pipeline_id,inbox_stage_id=s.inbox_stage_id,
                  title=LEFT(s.name,500),score=s.lead_score,score_breakdown=jsonb_build_object(
                    'doc_matches',LEAST(35,COALESCE(s.doc_matches,0)),'matched_files',LEAST(20,COALESCE(s.matched_files,0)*3),
                    'expertise',CASE WHEN s.expertise_number IS NOT NULL THEN 15 ELSE 0 END,
                    'participants',CASE WHEN s.customer_inn IS NOT NULL OR s.contractor_inn IS NOT NULL THEN 10 ELSE 0 END),
                  region=s.region_name,tags=jsonb_build_array('object','tender','awarded')
                    || CASE WHEN COALESCE(s.doc_matches,0)>0 OR COALESCE(s.matched_files,0)>0 THEN jsonb_build_array('documents_matched') ELSE '[]'::jsonb END
                    || CASE WHEN s.expertise_number IS NOT NULL THEN jsonb_build_array('expertise') ELSE '[]'::jsonb END,
                  recommended_pipeline_id=s.pipeline_id,developer_name=COALESCE(s.balance_holder,s.customer_name),
                  city=COALESCE(s.address,s.region_name),updated_at=NOW()
                FROM source s JOIN ext ON ext.source_key=s.object_key
                WHERE l.source_object_id=s.object_key AND l.disposition_status <> 'discarded' RETURNING l.id
            ), inserted AS (
                INSERT INTO crm_leads (external_entity_id,pipeline_id,inbox_stage_id,title,disposition_status,score,score_breakdown,
                  probability,expected_amount,owner_id,region,tags,recommended_pipeline_id,source_object_id,developer_name,city,created_at,updated_at)
                SELECT ext.id,s.pipeline_id,s.inbox_stage_id,LEFT(s.name,500),'active',s.lead_score,jsonb_build_object(
                  'doc_matches',LEAST(35,COALESCE(s.doc_matches,0)),'matched_files',LEAST(20,COALESCE(s.matched_files,0)*3),
                  'expertise',CASE WHEN s.expertise_number IS NOT NULL THEN 15 ELSE 0 END,
                  'participants',CASE WHEN s.customer_inn IS NOT NULL OR s.contractor_inn IS NOT NULL THEN 10 ELSE 0 END),
                  NULL,NULL,NULL,s.region_name,jsonb_build_array('object','tender','awarded')
                    || CASE WHEN COALESCE(s.doc_matches,0)>0 OR COALESCE(s.matched_files,0)>0 THEN jsonb_build_array('documents_matched') ELSE '[]'::jsonb END
                    || CASE WHEN s.expertise_number IS NOT NULL THEN jsonb_build_array('expertise') ELSE '[]'::jsonb END,
                  s.pipeline_id,s.object_key,COALESCE(s.balance_holder,s.customer_name),COALESCE(s.address,s.region_name),NOW(),NOW()
                FROM source s JOIN ext ON ext.source_key=s.object_key WHERE NOT EXISTS (
                  SELECT 1 FROM crm_leads l WHERE l.source_object_id=s.object_key AND l.disposition_status <> 'discarded') RETURNING id
            )
            SELECT (SELECT COUNT(*) FROM crm_objects_index) AS scanned,(SELECT COUNT(*) FROM source) AS eligible,
              (SELECT COUNT(*) FROM inserted) AS created,(SELECT COUNT(*) FROM updated) AS updated
            """, (min_days_left,))
        if rows:
            stats.update({key: int(rows[0].get(key) or 0) for key in ("scanned", "eligible", "created", "updated")})
            stats["skipped"] = max(0, stats["scanned"] - stats["eligible"])
    except Exception as exc:
        logger.warning(f"sync_awarded_object_leads batch: {exc}")
        stats.update(failed=1, error=str(exc))
    return stats
