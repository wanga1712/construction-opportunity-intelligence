"""Sync AI priorities from CRM objects to docs-daemon queue hints."""
from __future__ import annotations

from typing import Iterable

from src.services.object_lifecycle import is_awarded
from src.services.object_models import ObjectViewItem


DDL = """
CREATE TABLE IF NOT EXISTS crm_docs_priority_hints (
    id BIGSERIAL PRIMARY KEY,
    tender_id BIGINT NOT NULL,
    registry_type TEXT NOT NULL,
    contract_number TEXT,
    contour TEXT NOT NULL,
    ai_priority_score INTEGER NOT NULL DEFAULT 0,
    ai_profile TEXT,
    ai_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tender_id, registry_type)
);
CREATE INDEX IF NOT EXISTS ix_crm_docs_priority_hints_contour
    ON crm_docs_priority_hints(contour, ai_priority_score DESC, updated_at DESC);
"""


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


def sync_docs_priority_hints(tender_db, items: Iterable[ObjectViewItem]) -> dict:
    if not tender_db:
        return {"error": "Tender DB недоступна"}
    tender_db.execute_update(DDL)
    scanned = upserted = skipped = 0
    for item in items:
        scanned += 1
        if not item.tender_id or not item.registry_type:
            skipped += 1
            continue
        profile = _profile_for_segment(item.segment)
        contour = _contour_for_item(item)
        score = max(0, min(100, int(item.ai_priority_score or 0)))
        tender_db.execute_update(
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
                item.ai_priority_reason,
            ),
        )
        upserted += 1
    return {"scanned": scanned, "upserted": upserted, "skipped": skipped}

