"""Sync AI priorities from CRM objects to CRM-owned docs priority hints.

WRITE target: crm_db (not tender_monitor).
Runtime expects schema already applied via src/migrations/crm_docs_priority_hints.sql.
Missing table → FAIL CLOSED (capability unavailable). No runtime CREATE/ALTER.
"""
from __future__ import annotations

from typing import Iterable

from src.services.object_lifecycle import is_awarded
from src.services.object_models import ObjectViewItem
from src.services.schema_guard import require_relations


def _profile_for_segment(segment: str | None) -> str:
    seg = (segment or "").strip()
    if seg == "social":
        return "social_floor_light"
    if seg == "industrial":
        return "industrial_floor_light"
    if seg == "road_infrastructure":
        return "roads_drainage_composite"
    if seg == "residential":
        return "residential_basic"
    if seg == "commercial":
        return "commercial_mixed"
    return "generic"


def _contour_for_item(item: ObjectViewItem) -> str:
    return "awarded" if is_awarded(item) else "open"


def sync_docs_priority_hints(crm_db, items: Iterable[ObjectViewItem]) -> dict:
    """Upsert priority hints into CRM DB only. No auto-DDL."""
    if not crm_db:
        return {"error": "CRM DB недоступна", "status": "NOT_READY"}
    ok, missing = require_relations(crm_db, ["crm_docs_priority_hints"])
    if not ok:
        return {
            "error": "SCHEMA_NOT_READY",
            "status": "NOT_READY",
            "missing": missing,
            "write_role": "crm_db",
        }
    scanned = upserted = skipped = 0
    for item in items:
        scanned += 1
        if not item.tender_id or not item.registry_type:
            skipped += 1
            continue
        profile = _profile_for_segment(item.segment)
        contour = _contour_for_item(item)
        score = max(0, min(100, int(item.ai_priority_score or 0)))
        crm_db.execute_update(
            """
            INSERT INTO crm_docs_priority_hints (
                tender_id, registry_type, contract_number, contour,
                ai_priority_score, ai_profile, ai_reason, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tender_id, registry_type) DO UPDATE SET
                contract_number = EXCLUDED.contract_number,
                contour = EXCLUDED.contour,
                ai_priority_score = EXCLUDED.ai_priority_score,
                ai_profile = EXCLUDED.ai_profile,
                ai_reason = EXCLUDED.ai_reason,
                updated_at = NOW()
            """,
            (
                int(item.tender_id),
                str(item.registry_type),
                item.contract_number,
                contour,
                score,
                profile,
                getattr(item, "ai_reason", None) or "",
            ),
        )
        upserted += 1
    return {
        "scanned": scanned,
        "upserted": upserted,
        "skipped": skipped,
        "write_role": "crm_db",
        "status": "OK",
    }
