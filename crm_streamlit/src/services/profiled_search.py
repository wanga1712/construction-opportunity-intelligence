"""Profile-aware search decisions for multi-product CRM contours.

The same source object/tender can be useful for one product group and useless
for another. This service stores decisions at:

    object_key + search_profile + product_group

It deliberately does not delete objects globally.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "DB_PROFILED_SEARCH_SCHEMA.sql"
PROFILES_PATH = Path(__file__).resolve().parents[2] / "docs" / "DB_PROFILED_SEARCH_PROFILES_20260723.sql"


DECISION_GLOBAL_REJECT = "global_reject"
DECISION_PROFILE_REJECT = "profile_reject"
DECISION_PROFILE_KEEP = "profile_keep"
DECISION_PROFILE_REVIEW = "profile_review"
DECISION_NEEDS_DOCUMENTS = "needs_documents"
DECISION_DOCUMENTS_QUEUED = "documents_queued"
DECISION_DOCUMENTS_PARSED = "documents_parsed"
DECISION_QUALIFIED_LEAD = "qualified_lead"
DECISION_IN_WORK = "in_work"
DECISION_ARCHIVED = "archived"


@dataclass(frozen=True)
class ProductGroup:
    id: int
    code: str
    name: str
    description: str | None = None


@dataclass(frozen=True)
class SearchProfile:
    id: int
    code: str
    name: str
    description: str | None = None


@dataclass(frozen=True)
class ProfileDecision:
    object_key: str
    decision: str
    search_profile_id: int | None = None
    product_group_id: int | None = None
    registry_type: str | None = None
    tender_id: int | None = None
    source_type: str | None = None
    priority_score: int = 0
    reason: str | None = None
    matched_terms: list[Any] | None = None
    rejected_terms: list[Any] | None = None
    ai_payload: dict[str, Any] | None = None
    ai_model: str | None = None
    decided_by: str = "system"


class ProfiledSearchService:
    """Read/write layer for profile-specific relevance and AI learning."""

    def __init__(self, crm_db):
        self.crm_db = crm_db

    def available(self) -> bool:
        return bool(self.crm_db) and not self.crm_db.is_offline_mode()

    def ensure_schema(self) -> None:
        """Fail-closed: required profiled-search tables must already exist.

        No runtime CREATE/seed. Apply SQL under controlled migration only.
        """
        if not self.available():
            raise RuntimeError("CRM DB is not available")
        from src.services.schema_guard import require_relations_or_raise

        require_relations_or_raise(
            self.crm_db,
            [
                "crm_product_groups",
                "crm_search_profiles",
                "crm_search_rules",
                "crm_object_profile_decisions",
            ],
        )

    def product_groups(self) -> list[ProductGroup]:
        rows = self._query(
            """
            SELECT id, code, name, description
            FROM crm_product_groups
            WHERE is_active = TRUE
            ORDER BY name
            """
        )
        return [
            ProductGroup(
                id=int(row["id"]),
                code=str(row["code"]),
                name=str(row["name"]),
                description=row.get("description"),
            )
            for row in rows
        ]

    def search_profiles(self) -> list[SearchProfile]:
        rows = self._query(
            """
            SELECT id, code, name, description
            FROM crm_search_profiles
            WHERE is_active = TRUE
            ORDER BY name
            """
        )
        return [
            SearchProfile(
                id=int(row["id"]),
                code=str(row["code"]),
                name=str(row["name"]),
                description=row.get("description"),
            )
            for row in rows
        ]

    def profile_groups(self) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT
                spg.id,
                sp.id AS search_profile_id,
                sp.code AS search_profile_code,
                sp.name AS search_profile_name,
                pg.id AS product_group_id,
                pg.code AS product_group_code,
                pg.name AS product_group_name,
                spg.priority_weight
            FROM crm_search_profile_groups spg
            JOIN crm_search_profiles sp ON sp.id = spg.search_profile_id
            JOIN crm_product_groups pg ON pg.id = spg.product_group_id
            WHERE spg.is_active = TRUE
              AND sp.is_active = TRUE
              AND pg.is_active = TRUE
            ORDER BY sp.name, pg.name
            """
        )

    def decisions_for_object(self, object_key: str) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT
                d.*,
                sp.code AS search_profile_code,
                sp.name AS search_profile_name,
                pg.code AS product_group_code,
                pg.name AS product_group_name
            FROM crm_object_profile_decisions d
            LEFT JOIN crm_search_profiles sp ON sp.id = d.search_profile_id
            LEFT JOIN crm_product_groups pg ON pg.id = d.product_group_id
            WHERE d.object_key = %s
            ORDER BY d.priority_score DESC, d.updated_at DESC
            """,
            (object_key,),
        )

    def upsert_decision(self, decision: ProfileDecision) -> dict[str, Any] | None:
        priority = max(0, min(100, int(decision.priority_score or 0)))
        rows = self._query(
            """
            INSERT INTO crm_object_profile_decisions (
                object_key,
                registry_type,
                tender_id,
                source_type,
                search_profile_id,
                product_group_id,
                decision,
                priority_score,
                reason,
                matched_terms,
                rejected_terms,
                ai_payload,
                ai_model,
                decided_by,
                decided_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, NOW(), NOW()
            )
            ON CONFLICT (object_key, search_profile_id, product_group_id)
            DO UPDATE SET
                registry_type = EXCLUDED.registry_type,
                tender_id = EXCLUDED.tender_id,
                source_type = EXCLUDED.source_type,
                decision = EXCLUDED.decision,
                priority_score = EXCLUDED.priority_score,
                reason = EXCLUDED.reason,
                matched_terms = EXCLUDED.matched_terms,
                rejected_terms = EXCLUDED.rejected_terms,
                ai_payload = EXCLUDED.ai_payload,
                ai_model = EXCLUDED.ai_model,
                decided_by = EXCLUDED.decided_by,
                decided_at = NOW(),
                updated_at = NOW()
            RETURNING *
            """,
            (
                decision.object_key,
                decision.registry_type,
                decision.tender_id,
                decision.source_type,
                decision.search_profile_id,
                decision.product_group_id,
                decision.decision,
                priority,
                decision.reason,
                json.dumps(decision.matched_terms or [], ensure_ascii=False),
                json.dumps(decision.rejected_terms or [], ensure_ascii=False),
                json.dumps(decision.ai_payload or {}, ensure_ascii=False),
                decision.ai_model,
                decision.decided_by,
            ),
        )
        return rows[0] if rows else None

    def add_training_event(
        self,
        *,
        event_type: str,
        object_key: str | None = None,
        registry_type: str | None = None,
        tender_id: int | None = None,
        search_profile_id: int | None = None,
        product_group_id: int | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        comment: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any] | None:
        rows = self._query(
            """
            INSERT INTO crm_ai_training_events (
                object_key,
                registry_type,
                tender_id,
                search_profile_id,
                product_group_id,
                event_type,
                old_value,
                new_value,
                comment,
                created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                object_key,
                registry_type,
                tender_id,
                search_profile_id,
                product_group_id,
                event_type,
                json.dumps(old_value or {}, ensure_ascii=False),
                json.dumps(new_value or {}, ensure_ascii=False),
                comment,
                created_by,
            ),
        )
        return rows[0] if rows else None

    def bulk_upsert_decisions(self, decisions: Iterable[ProfileDecision]) -> int:
        count = 0
        for decision in decisions:
            if self.upsert_decision(decision):
                count += 1
        return count

    def _query(self, query: str, params: tuple | None = None) -> list[dict[str, Any]]:
        if not self.available():
            return []
        return list(self.crm_db.execute_query(query, params))

