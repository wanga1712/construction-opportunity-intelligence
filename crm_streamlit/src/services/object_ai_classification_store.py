"""Persistent AI object classification storage in CRM DB.

The older CRM layer kept AI category labels and priority as append-only JSONL
files.  We keep those files as a local audit log, but the durable state should
live in the CRM database so cards, background jobs and future company analytics
see the same truth.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from loguru import logger
from psycopg2.extras import Json

from modules.crm.crm_database import CrmDatabaseManager
from src.services.object_category_labels import object_label_key, object_label_keys, segment_from_label
from src.services.object_models import ObjectViewItem


DDL = """
CREATE TABLE IF NOT EXISTS crm_object_ai_classifications (
    id BIGSERIAL PRIMARY KEY,
    object_key TEXT NOT NULL,
    tender_id BIGINT,
    registry_type TEXT,
    contract_number TEXT,
    expertise_number TEXT,
    segment TEXT,
    label TEXT,
    primary_class TEXT,
    subcategory TEXT,
    object_type TEXT,
    object_subtype TEXT,
    social_status TEXT,
    work_type TEXT,
    project_stage TEXT,
    stage_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    stage_primary TEXT,
    stage_reason TEXT,
    infrastructure_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    priority_score INTEGER NOT NULL DEFAULT 0,
    delivery_chance TEXT,
    volume_signal TEXT,
    sales_action TEXT,
    model_name TEXT,
    model_version TEXT,
    classification_confidence INTEGER NOT NULL DEFAULT 0,
    classification_reason TEXT,
    manager_corrected BOOLEAN NOT NULL DEFAULT FALSE,
    manager_correction JSONB,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE crm_object_ai_classifications
    ADD COLUMN IF NOT EXISTS primary_class TEXT,
    ADD COLUMN IF NOT EXISTS subcategory TEXT,
    ADD COLUMN IF NOT EXISTS object_type TEXT,
    ADD COLUMN IF NOT EXISTS object_subtype TEXT,
    ADD COLUMN IF NOT EXISTS social_status TEXT,
    ADD COLUMN IF NOT EXISTS work_type TEXT,
    ADD COLUMN IF NOT EXISTS project_stage TEXT,
    ADD COLUMN IF NOT EXISTS stage_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS stage_primary TEXT,
    ADD COLUMN IF NOT EXISTS stage_reason TEXT,
    ADD COLUMN IF NOT EXISTS infrastructure_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS sales_action TEXT,
    ADD COLUMN IF NOT EXISTS model_name TEXT,
    ADD COLUMN IF NOT EXISTS model_version TEXT,
    ADD COLUMN IF NOT EXISTS classification_confidence INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS classification_reason TEXT,
    ADD COLUMN IF NOT EXISTS manager_corrected BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS manager_correction JSONB,
    ADD COLUMN IF NOT EXISTS manager_next_step TEXT,
    ADD COLUMN IF NOT EXISTS talk_track TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_crm_object_ai_classifications_object_key
    ON crm_object_ai_classifications(object_key);
CREATE INDEX IF NOT EXISTS ix_crm_object_ai_classifications_contract
    ON crm_object_ai_classifications(contract_number);
CREATE INDEX IF NOT EXISTS ix_crm_object_ai_classifications_expertise
    ON crm_object_ai_classifications(expertise_number);
CREATE INDEX IF NOT EXISTS ix_crm_object_ai_classifications_segment
    ON crm_object_ai_classifications(segment);
CREATE INDEX IF NOT EXISTS ix_crm_object_ai_classifications_priority
    ON crm_object_ai_classifications(priority_score DESC);
"""
_SCHEMA_INITIALIZED = False


def _crm_db() -> Optional[CrmDatabaseManager]:
    db = CrmDatabaseManager.get_instance()
    if db and db.is_connected():
        return db
    return None


def _table_exists(db: CrmDatabaseManager) -> bool:
    try:
        rows = db.execute_query("SELECT to_regclass('public.crm_object_ai_classifications') AS reg")
    except Exception:
        return False
    if not rows:
        return False
    reg = rows[0].get("reg") if isinstance(rows[0], dict) else None
    return bool(reg)


def ensure_schema(crm_db: Optional[CrmDatabaseManager] = None) -> bool:
    global _SCHEMA_INITIALIZED
    db = crm_db or _crm_db()
    if not db:
        return False
    if _SCHEMA_INITIALIZED:
        return True
    if _table_exists(db):
        _SCHEMA_INITIALIZED = True
        return True
    try:
        db.execute_update(DDL)
        _SCHEMA_INITIALIZED = True
        return True
    except Exception as exc:
        # Do not block the UI flow when DB is under load.
        logger.warning(f"ensure_schema ai_classifications failed: {exc}")
        return False


def load_ai_classifications(crm_db: Optional[CrmDatabaseManager] = None) -> Dict[str, dict]:
    db = crm_db or _crm_db()
    if not db:
        return {}
    if not ensure_schema(db):
        return {}
    try:
        rows = db.execute_query(
            """
            SELECT *
            FROM crm_object_ai_classifications
            ORDER BY updated_at ASC, id ASC
            """
        )
    except Exception as exc:
        logger.warning(f"load_ai_classifications query failed: {exc}")
        return {}
    out: Dict[str, dict] = {}
    for row in rows:
        key = str(row.get("object_key") or "")
        if key:
            out[key] = row
            out[f"object:{key}"] = row
        registry_type = str(row.get("registry_type") or "")
        tender_id = row.get("tender_id")
        if registry_type and tender_id:
            out[f"{registry_type}:{tender_id}"] = row
        contract_number = str(row.get("contract_number") or "")
        if contract_number:
            out[f"contract:{contract_number}"] = row
        expertise_number = str(row.get("expertise_number") or "")
        if expertise_number:
            out[f"expertise:{expertise_number}"] = row
    return out


def apply_ai_classifications(items: Iterable[ObjectViewItem], crm_db: Optional[CrmDatabaseManager] = None) -> None:
    rows = load_ai_classifications(crm_db)
    if not rows:
        return
    for item in items:
        row = next((rows.get(key) for key in object_label_keys(item) if rows.get(key)), None)
        if not row:
            continue
        segment = row.get("segment") or segment_from_label(row.get("label"))
        if segment:
            item.segment = segment
        item.ai_primary_class = row.get("primary_class")
        item.ai_subcategory = row.get("subcategory")
        item.ai_object_type = row.get("object_type")
        item.ai_object_subtype = row.get("object_subtype")
        item.ai_social_status = row.get("social_status")
        item.ai_work_type = row.get("work_type")
        item.ai_project_stage = row.get("project_stage")
        item.ai_stage_signals = row.get("stage_signals") or []
        item.ai_stage_reason = row.get("stage_reason")
        item.ai_infrastructure_tags = row.get("infrastructure_tags") or []
        try:
            item.ai_priority_score = int(row.get("priority_score") or 0)
        except Exception:
            item.ai_priority_score = 0
        item.ai_priority_reason = row.get("classification_reason")
        item.ai_delivery_chance = row.get("delivery_chance")
        from src.services.object_ai_fallbacks import sanitize_volume_signal

        item.ai_volume_signal = sanitize_volume_signal(item, str(row.get("volume_signal") or ""))
        item.ai_sales_action = row.get("sales_action")
        item.ai_manager_next_step = row.get("manager_next_step")
        item.ai_talk_track = row.get("talk_track")
        item.ai_classification_confidence = int(row.get("classification_confidence") or 0)


def save_ai_classification(
    item: ObjectViewItem,
    result: dict,
    *,
    label: Optional[str] = None,
    source: str = "ai_batch",
    manager_corrected: bool = False,
    manager_correction: Optional[dict] = None,
    crm_db: Optional[CrmDatabaseManager] = None,
) -> dict:
    db = crm_db or _crm_db()
    if not db:
        return {}
    if not ensure_schema(db):
        return {}
    object_key = object_label_key(item)
    label_value = label or result.get("label")
    segment = result.get("segment") or segment_from_label(label_value) or item.segment or "other"
    try:
        priority = max(0, min(100, int(result.get("priority_score") or result.get("priority") or 0)))
    except Exception:
        priority = 0
    try:
        confidence = max(0, min(100, int(result.get("confidence") or result.get("classification_confidence") or 0)))
    except Exception:
        confidence = 0

    tags = result.get("infrastructure_tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]

    row = {
        "object_key": object_key,
        "tender_id": item.tender_id,
        "registry_type": item.registry_type,
        "contract_number": item.contract_number,
        "expertise_number": item.expertise_number,
        "segment": segment,
        "label": label_value,
        "primary_class": result.get("primary_class"),
        "subcategory": result.get("subcategory"),
        "object_type": result.get("object_type"),
        "object_subtype": result.get("object_subtype"),
        "social_status": result.get("social_status"),
        "work_type": result.get("work_type"),
        "project_stage": result.get("project_stage"),
        "stage_signals": Json(result.get("stage_signals") or []),
        "stage_primary": result.get("stage_primary"),
        "stage_reason": result.get("stage_reason"),
        "infrastructure_tags": Json(tags),
        "priority_score": priority,
        "delivery_chance": result.get("delivery_chance"),
        "volume_signal": result.get("volume_signal"),
        "sales_action": result.get("sales_action"),
        "manager_next_step": result.get("manager_next_step"),
        "talk_track": result.get("talk_track"),
        "model_name": result.get("model_name"),
        "model_version": result.get("model_version"),
        "classification_confidence": confidence,
        "classification_reason": result.get("classification_reason") or result.get("reason"),
        "manager_corrected": manager_corrected,
        "manager_correction": Json(manager_correction) if manager_correction is not None else None,
        "source": source,
    }
    db.execute_update(
        """
        INSERT INTO crm_object_ai_classifications (
            object_key, tender_id, registry_type, contract_number, expertise_number,
            segment, label, primary_class, subcategory, object_type, object_subtype,
            social_status, work_type, project_stage, stage_signals, stage_primary, stage_reason, infrastructure_tags,
            priority_score, delivery_chance, volume_signal, sales_action,
            manager_next_step, talk_track,
            model_name, model_version,
            classification_confidence, classification_reason,
            manager_corrected, manager_correction, source
        )
        VALUES (
            %(object_key)s, %(tender_id)s, %(registry_type)s, %(contract_number)s, %(expertise_number)s,
            %(segment)s, %(label)s, %(primary_class)s, %(subcategory)s, %(object_type)s, %(object_subtype)s,
            %(social_status)s, %(work_type)s, %(project_stage)s, %(stage_signals)s::jsonb, %(stage_primary)s, %(stage_reason)s, %(infrastructure_tags)s::jsonb,
            %(priority_score)s, %(delivery_chance)s, %(volume_signal)s, %(sales_action)s,
            %(manager_next_step)s, %(talk_track)s,
            %(model_name)s, %(model_version)s,
            %(classification_confidence)s, %(classification_reason)s,
            %(manager_corrected)s, %(manager_correction)s::jsonb, %(source)s
        )
        ON CONFLICT (object_key) DO UPDATE SET
            tender_id = EXCLUDED.tender_id,
            registry_type = EXCLUDED.registry_type,
            contract_number = EXCLUDED.contract_number,
            expertise_number = EXCLUDED.expertise_number,
            segment = EXCLUDED.segment,
            label = EXCLUDED.label,
            primary_class = EXCLUDED.primary_class,
            subcategory = EXCLUDED.subcategory,
            object_type = EXCLUDED.object_type,
            object_subtype = EXCLUDED.object_subtype,
            social_status = EXCLUDED.social_status,
            work_type = EXCLUDED.work_type,
            project_stage = EXCLUDED.project_stage,
            stage_signals = EXCLUDED.stage_signals,
            stage_primary = EXCLUDED.stage_primary,
            stage_reason = EXCLUDED.stage_reason,
            infrastructure_tags = EXCLUDED.infrastructure_tags,
            priority_score = EXCLUDED.priority_score,
            delivery_chance = EXCLUDED.delivery_chance,
            volume_signal = EXCLUDED.volume_signal,
            sales_action = EXCLUDED.sales_action,
            manager_next_step = EXCLUDED.manager_next_step,
            talk_track = EXCLUDED.talk_track,
            model_name = EXCLUDED.model_name,
            model_version = EXCLUDED.model_version,
            classification_confidence = EXCLUDED.classification_confidence,
            classification_reason = EXCLUDED.classification_reason,
            manager_corrected = crm_object_ai_classifications.manager_corrected OR EXCLUDED.manager_corrected,
            manager_correction = COALESCE(EXCLUDED.manager_correction, crm_object_ai_classifications.manager_correction),
            source = EXCLUDED.source,
            updated_at = now()
        """,
        row,
    )
    return row
