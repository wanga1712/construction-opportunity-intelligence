"""Bridge between CRM object index and CRM lead state.

In the UI, the "Objects" page is the manager's lead queue.  The `crm_leads`
table is used as a persistent state layer: taken in work, score, routing and
future conversion to opportunities.
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

from loguru import logger

from src.services.object_lifecycle import is_awarded
from src.services.object_models import ObjectViewItem
from src.services.object_leads_sync import (
    AWARDED_MIN_DAYS_LEFT,
    sync_awarded_object_leads,
)


def upsert_object_lead(crm_db, item: ObjectViewItem, *, mark_taken: bool = False) -> str:
    """Create/update one lead-state row for an object.

    Returns `created` or `updated`.
    """
    if not _crm_ok(crm_db):
        raise RuntimeError("CRM DB unavailable")

    pipeline_id = _pipeline_id(crm_db, item)
    inbox_stage_id = _inbox_stage_id(crm_db, "reviewed" if is_awarded(item) else "new")
    external_entity_id = _upsert_external_entity(crm_db, item)

    existing = crm_db.execute_query(
        """
        SELECT id, disposition_status, owner_id
        FROM crm_leads
        WHERE source_object_id = %s
        ORDER BY id
        LIMIT 1
        """,
        (item.key,),
    )

    payload = _lead_payload(item, pipeline_id, inbox_stage_id, mark_taken=mark_taken)
    if existing:
        lead_id = existing[0]["id"]
        crm_db.execute_update(
            """
            UPDATE crm_leads SET
                external_entity_id = %s,
                pipeline_id = %s,
                inbox_stage_id = %s,
                title = %s,
                disposition_status = CASE
                    WHEN disposition_status = 'discarded' THEN disposition_status
                    ELSE 'active'
                END,
                score = %s,
                score_breakdown = %s::jsonb,
                expected_amount = COALESCE(expected_amount, %s),
                region = %s,
                tags = %s::jsonb,
                recommended_pipeline_id = %s,
                developer_name = %s,
                city = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                external_entity_id,
                pipeline_id,
                inbox_stage_id,
                payload["title"],
                payload["score"],
                json.dumps(payload["score_breakdown"], ensure_ascii=False),
                payload["expected_amount"],
                payload["region"],
                json.dumps(payload["tags"], ensure_ascii=False),
                pipeline_id,
                payload["developer_name"],
                payload["city"],
                lead_id,
            ),
        )
        return "updated"

    crm_db.execute_update(
        """
        INSERT INTO crm_leads (
            external_entity_id, pipeline_id, inbox_stage_id, title,
            disposition_status, score, score_breakdown, probability,
            expected_amount, owner_id, region, tags, recommended_pipeline_id,
            source_object_id, developer_name, city, created_at, updated_at
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s::jsonb, %s,
            %s, %s, %s, %s::jsonb, %s,
            %s, %s, %s, NOW(), NOW()
        )
        """,
        (
            external_entity_id,
            pipeline_id,
            inbox_stage_id,
            payload["title"],
            "active",
            payload["score"],
            json.dumps(payload["score_breakdown"], ensure_ascii=False),
            payload["probability"],
            payload["expected_amount"],
            None,
            payload["region"],
            json.dumps(payload["tags"], ensure_ascii=False),
            pipeline_id,
            item.key,
            payload["developer_name"],
            payload["city"],
        ),
    )
    return "created"


def object_lead_status(crm_db, object_key: str) -> Optional[dict]:
    if not _crm_ok(crm_db):
        return None
    rows = crm_db.execute_query(
        """
        SELECT id, disposition_status, owner_id, pipeline_id, inbox_stage_id, score, updated_at
        FROM crm_leads
        WHERE source_object_id = %s
        ORDER BY id
        LIMIT 1
        """,
        (object_key,),
    )
    return dict(rows[0]) if rows else None


def _crm_ok(crm_db) -> bool:
    return bool(crm_db and not crm_db.is_offline_mode())


def _pipeline_id(crm_db, item: ObjectViewItem) -> int:
    rt = (item.registry_type or "").lower()
    code = "procurement_223fz" if "223" in rt else "procurement_44fz"
    rows = crm_db.execute_query(
        "SELECT id FROM crm_pipelines WHERE code = %s AND is_active = TRUE LIMIT 1",
        (code,),
    )
    if rows:
        return int(rows[0]["id"])
    rows = crm_db.execute_query(
        "SELECT id FROM crm_pipelines WHERE code = 'materials_supply' LIMIT 1",
    )
    return int(rows[0]["id"]) if rows else 5


def _inbox_stage_id(crm_db, stage_key: str) -> int:
    rows = crm_db.execute_query(
        "SELECT id FROM crm_lead_inbox_stages WHERE stage_key = %s LIMIT 1",
        (stage_key,),
    )
    if rows:
        return int(rows[0]["id"])
    return 2 if stage_key == "reviewed" else 1


def _upsert_external_entity(crm_db, item: ObjectViewItem) -> int:
    payload = {
        "object_key": item.key,
        "registry_type": item.registry_type,
        "tender_id": item.tender_id,
        "name": item.name,
        "address": item.address,
        "region": item.region,
        "region_id": item.region_id,
        "status": item.status,
        "contract_number": item.contract_number,
        "expertise_number": item.expertise_number,
        "doc_matches": item.doc_matches,
        "matched_files": item.matched_files,
        "delivery_start_date": item.delivery_start_date,
        "delivery_end_date": item.delivery_end_date,
        "end_date": item.end_date,
        "customer_name": item.customer_name,
        "customer_inn": item.customer_inn,
        "contractor_name": item.contractor_name,
        "contractor_inn": item.contractor_inn,
        "balance_holder": item.balance_holder,
        "segment": item.segment,
        "source": "crm_objects_index",
    }
    rows = crm_db.execute_query(
        """
        INSERT INTO crm_external_entities (source_type, source_key, payload, updated_at)
        VALUES ('tender_object', %s, %s::jsonb, NOW())
        ON CONFLICT (source_type, source_key)
        DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
        RETURNING id
        """,
        (item.key, json.dumps(payload, ensure_ascii=False)),
    )
    return int(rows[0]["id"])


def _lead_payload(
    item: ObjectViewItem,
    pipeline_id: int,
    inbox_stage_id: int,
    *,
    mark_taken: bool = False,
) -> dict:
    score, breakdown = _score(item)
    tags = ["object", "tender"]
    if is_awarded(item):
        tags.append("awarded")
    if item.doc_matches or item.matched_files:
        tags.append("documents_matched")
    if item.expertise_number:
        tags.append("expertise")
    if mark_taken:
        tags.append("in_work")
    return {
        "title": (item.name or item.key)[:500],
        "score": score,
        "score_breakdown": breakdown,
        "probability": None,
        "expected_amount": None,
        "region": item.region,
        "tags": tags,
        "developer_name": item.balance_holder or item.customer_name,
        "city": item.address or item.region,
        "pipeline_id": pipeline_id,
        "inbox_stage_id": inbox_stage_id,
    }


def _score(item: ObjectViewItem) -> tuple[int, dict]:
    breakdown = {
        "doc_matches": min(35, int(item.doc_matches or 0)),
        "matched_files": min(20, int(item.matched_files or 0) * 3),
        "expertise": 15 if item.expertise_number else 0,
        "participants": 10 if (item.customer_inn or item.contractor_inn) else 0,
        "ai_priority": min(20, int(item.ai_priority_score or 0) // 5),
    }
    return min(100, sum(breakdown.values())), breakdown


