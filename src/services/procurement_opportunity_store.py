"""Persistence helpers for procurement opportunity classification.

This module owns the CRM-side SQL for the new universal classifier.  It never
creates runtime DDL: all three tables are provisioned by
``src/migrations/procurement_opportunity_classifier_1.sql``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.services.procurement_opportunity_ai import (
    auto_category_code,
    auto_subcategory_code,
    normalize_name,
)


REQUIRED_TABLES = (
    "crm_procurement_classifications",
    "crm_procurement_opportunities",
    "crm_product_taxonomy_discovery",
)


def make_object_key(registry_type: Any, tender_id: Any) -> str:
    return f"tender:{registry_type}:{tender_id}"


def ensure_schema(crm_db: Any) -> bool:
    """Fail-closed check that the migration has been applied."""
    if not crm_db:
        return False
    for table in REQUIRED_TABLES:
        try:
            rows = crm_db.execute_query(
                f"SELECT to_regclass('public.{table}') AS reg"
            )
        except Exception:
            return False
        if not rows or not rows[0].get("reg"):
            return False
    return True


def load_active_taxonomy(crm_db: Any) -> List[Dict[str, Any]]:
    rows = crm_db.execute_query(
        """
        SELECT
            c.category_code,
            c.category_name,
            s.subcategory_code,
            s.subcategory_name
        FROM crm_product_categories c
        LEFT JOIN crm_product_subcategories s
          ON s.category_id = c.id
         AND s.is_active = TRUE
        WHERE c.is_active = TRUE
        ORDER BY c.sort_order, c.category_code, s.sort_order, s.subcategory_code
        """
    ) or []
    categories: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("category_code") or "").strip()
        if not code:
            continue
        category = categories.setdefault(
            code,
            {
                "category_code": code,
                "category_name": str(row.get("category_name") or "").strip(),
                "subcategories": [],
            },
        )
        sub_code = str(row.get("subcategory_code") or "").strip()
        sub_name = str(row.get("subcategory_name") or "").strip()
        if sub_code and sub_name:
            category["subcategories"].append(
                {"subcategory_code": sub_code, "subcategory_name": sub_name}
            )
    return list(categories.values())


def load_pending_procurements(crm_db: Any, limit: int) -> List[Dict[str, Any]]:
    return crm_db.execute_query(
        """
        SELECT
            p.id,
            p.source_table,
            p.source_id,
            p.contract_number,
            p.auction_name,
            p.initial_price,
            p.customer,
            p.okpd_code,
            p.okpd_name
        FROM crm_procurements p
        LEFT JOIN crm_procurement_classifications c
          ON c.object_key = 'tender:' || p.source_table || ':' || p.source_id::text
        WHERE COALESCE(p.auction_name, '') <> ''
        ORDER BY (c.object_key IS NULL) DESC, p.id
        LIMIT %s
        """,
        (limit,),
    ) or []


def load_classification_hashes(crm_db: Any) -> Dict[str, str]:
    rows = crm_db.execute_query(
        "SELECT object_key, source_hash FROM crm_procurement_classifications"
    ) or []
    return {
        str(row.get("object_key") or ""): str(row.get("source_hash") or "")
        for row in rows
        if row.get("object_key")
    }


def load_opportunity_signatures(crm_db: Any, object_key: str) -> Set[Tuple[str, str]]:
    rows = crm_db.execute_query(
        """
        SELECT category_code, subcategory_code
        FROM crm_procurement_opportunities
        WHERE object_key = %s
        """,
        (object_key,),
    ) or []
    return {
        (str(row.get("category_code") or ""), str(row.get("subcategory_code") or ""))
        for row in rows
    }


def load_existing_object_ai(crm_db: Any, object_key: str, tender_id: Any, registry_type: Any) -> Dict[str, Any]:
    rows = crm_db.execute_query(
        """
        SELECT
            primary_class,
            subcategory,
            object_type,
            object_subtype,
            work_type,
            classification_confidence
        FROM crm_object_ai_classifications
        WHERE object_key = %s
           OR (registry_type = %s AND tender_id = %s)
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (object_key, registry_type, tender_id),
    ) or []
    return dict(rows[0]) if rows else {}


def save_classification(
    crm_db: Any,
    *,
    object_key: str,
    tender_id: Any,
    registry_type: Any,
    procurement_mode: str,
    object_present: bool,
    object_payload: Dict[str, Any],
    classification_status: str,
    classification_confidence: float,
    source_hash: str,
    model_name: Optional[str],
    model_version: Optional[str],
) -> None:
    crm_db.execute_update(
        """
        INSERT INTO crm_procurement_classifications (
            object_key,
            tender_id,
            registry_type,
            procurement_mode,
            object_present,
            primary_class,
            object_subcategory,
            object_type,
            object_subtype,
            work_type,
            classification_status,
            classification_confidence,
            model_name,
            model_version,
            source_hash,
            created_at,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            NOW(), NOW()
        )
        ON CONFLICT (object_key) DO UPDATE SET
            tender_id = EXCLUDED.tender_id,
            registry_type = EXCLUDED.registry_type,
            procurement_mode = EXCLUDED.procurement_mode,
            object_present = EXCLUDED.object_present,
            primary_class = EXCLUDED.primary_class,
            object_subcategory = EXCLUDED.object_subcategory,
            object_type = EXCLUDED.object_type,
            object_subtype = EXCLUDED.object_subtype,
            work_type = EXCLUDED.work_type,
            classification_status = EXCLUDED.classification_status,
            classification_confidence = EXCLUDED.classification_confidence,
            model_name = EXCLUDED.model_name,
            model_version = EXCLUDED.model_version,
            source_hash = EXCLUDED.source_hash,
            updated_at = NOW()
        """,
        (
            object_key,
            tender_id,
            registry_type,
            procurement_mode,
            object_present,
            object_payload.get("primary_class"),
            object_payload.get("subcategory"),
            object_payload.get("object_type"),
            object_payload.get("object_subtype"),
            object_payload.get("work_type"),
            classification_status,
            classification_confidence,
            model_name,
            model_version,
            source_hash,
        ),
    )


def replace_opportunities(
    crm_db: Any,
    *,
    object_key: str,
    tender_id: Any,
    registry_type: Any,
    procurement_mode: str,
    opportunities: Sequence[Dict[str, Any]],
    model_name: Optional[str],
    model_version: Optional[str],
) -> None:
    crm_db.execute_update(
        "DELETE FROM crm_procurement_opportunities WHERE object_key = %s",
        (object_key,),
    )
    for opportunity in opportunities:
        crm_db.execute_update(
            """
            INSERT INTO crm_procurement_opportunities (
                object_key,
                tender_id,
                registry_type,
                procurement_mode,
                category_code,
                category_name,
                subcategory_code,
                subcategory_name,
                product_name,
                quantity,
                unit,
                taxonomy_action,
                confidence,
                repeat_signature,
                model_name,
                model_version,
                created_at,
                updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                NOW(), NOW()
            )
            ON CONFLICT (object_key, category_code, subcategory_code, product_name)
            DO UPDATE SET
                category_name = EXCLUDED.category_name,
                subcategory_name = EXCLUDED.subcategory_name,
                procurement_mode = EXCLUDED.procurement_mode,
                quantity = EXCLUDED.quantity,
                unit = EXCLUDED.unit,
                taxonomy_action = EXCLUDED.taxonomy_action,
                confidence = EXCLUDED.confidence,
                repeat_signature = EXCLUDED.repeat_signature,
                model_name = EXCLUDED.model_name,
                model_version = EXCLUDED.model_version,
                updated_at = NOW()
            """,
            (
                object_key,
                tender_id,
                registry_type,
                procurement_mode,
                opportunity.get("category_code"),
                opportunity.get("category_name"),
                opportunity.get("subcategory_code"),
                opportunity.get("subcategory_name"),
                opportunity.get("product_name"),
                opportunity.get("quantity"),
                opportunity.get("unit"),
                opportunity.get("taxonomy_action"),
                opportunity.get("confidence"),
                opportunity.get("repeat_signature"),
                model_name,
                model_version,
            ),
        )


def record_discovery(
    crm_db: Any,
    *,
    parent_name: str,
    subcategory_name: str,
    sample_product_name: str,
    confidence: float,
    total_amount: float,
    is_new_procurement: bool,
) -> None:
    """Accumulate a taxonomy candidate.

    ``is_new_procurement`` is True only for a procurement that has not already
    contributed this exact parent/subcategory signature.  Reprocessing the same
    procurement therefore never inflates counts, amounts or confidence sums.
    """
    parent_norm = normalize_name(parent_name)
    subcategory_norm = normalize_name(subcategory_name)
    crm_db.execute_update(
        """
        INSERT INTO crm_product_taxonomy_discovery (
            parent_name,
            parent_name_norm,
            subcategory_name,
            subcategory_name_norm,
            sample_product_name,
            procurement_count,
            total_amount,
            confidence_sum,
            status,
            first_seen_at,
            last_seen_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            'candidate',
            NOW(), NOW()
        )
        ON CONFLICT (parent_name_norm, subcategory_name_norm) DO UPDATE SET
            sample_product_name = EXCLUDED.sample_product_name,
            procurement_count =
                crm_product_taxonomy_discovery.procurement_count
                + EXCLUDED.procurement_count,
            total_amount =
                crm_product_taxonomy_discovery.total_amount
                + EXCLUDED.total_amount,
            confidence_sum =
                crm_product_taxonomy_discovery.confidence_sum
                + EXCLUDED.confidence_sum,
            last_seen_at = NOW()
        """,
        (
            parent_name,
            parent_norm,
            subcategory_name,
            subcategory_norm,
            sample_product_name,
            1 if is_new_procurement else 0,
            float(total_amount or 0) if is_new_procurement else 0,
            float(confidence or 0) if is_new_procurement else 0,
        ),
    )


def promote_discovery(crm_db: Any) -> List[Dict[str, Any]]:
    """Promote candidates that satisfy the hard rule.

    Rule: distinct procurements >= 3 AND average confidence >= 0.80.
    No tunable thresholds are accepted from callers.
    """
    candidates = crm_db.execute_query(
        """
        SELECT
            id,
            parent_name,
            parent_name_norm,
            subcategory_name,
            subcategory_name_norm,
            sample_product_name,
            procurement_count,
            confidence_sum
        FROM crm_product_taxonomy_discovery
        WHERE status = 'candidate'
          AND procurement_count >= 3
          AND (confidence_sum / NULLIF(procurement_count, 0)) >= 0.80
        """
    ) or []

    promoted: List[Dict[str, Any]] = []
    for row in candidates:
        parent_name = str(row.get("parent_name") or "").strip()
        subcategory_name = str(row.get("subcategory_name") or "").strip()
        sample_product_name = str(row.get("sample_product_name") or "").strip()
        category_code = auto_category_code(parent_name)
        subcategory_code = auto_subcategory_code(parent_name, subcategory_name)

        crm_db.execute_update(
            """
            INSERT INTO crm_product_categories (
                contour_code, category_code, category_name, sort_order, is_active
            ) VALUES ('procurement', %s, %s, 9999, TRUE)
            ON CONFLICT (contour_code, category_code) DO UPDATE SET
                category_name = EXCLUDED.category_name,
                is_active = TRUE,
                updated_at = NOW()
            """,
            (category_code, parent_name),
        )
        category_rows = crm_db.execute_query(
            """
            SELECT id
            FROM crm_product_categories
            WHERE contour_code = 'procurement' AND category_code = %s
            """,
            (category_code,),
        ) or []
        if not category_rows:
            continue
        category_id = category_rows[0].get("id")

        crm_db.execute_update(
            """
            INSERT INTO crm_product_subcategories (
                category_id, subcategory_code, subcategory_name, source, sort_order, is_active
            ) VALUES (%s, %s, %s, 'auto_discovery', 100, TRUE)
            ON CONFLICT (category_id, subcategory_code) DO UPDATE SET
                subcategory_name = EXCLUDED.subcategory_name,
                is_active = TRUE,
                updated_at = NOW()
            """,
            (category_id, subcategory_code, subcategory_name),
        )
        subcategory_rows = crm_db.execute_query(
            """
            SELECT id
            FROM crm_product_subcategories
            WHERE category_id = %s AND subcategory_code = %s
            """,
            (category_id, subcategory_code),
        ) or []
        if subcategory_rows:
            subcategory_id = subcategory_rows[0].get("id")
            if sample_product_name:
                crm_db.execute_update(
                    """
                    INSERT INTO crm_product_subcategory_terms (
                        subcategory_id, term_type, phrase, weight, source, is_active
                    ) VALUES (%s, 'search', %s, 100, 'auto_discovery', TRUE)
                    ON CONFLICT (subcategory_id, term_type, phrase) DO UPDATE SET
                        is_active = TRUE,
                        updated_at = NOW()
                    """,
                    (subcategory_id, sample_product_name),
                )

        crm_db.execute_update(
            """
            UPDATE crm_product_taxonomy_discovery
            SET status = 'promoted', promoted_at = NOW()
            WHERE id = %s
            """,
            (row.get("id"),),
        )
        promoted.append(
            {
                "parent_name": parent_name,
                "subcategory_name": subcategory_name,
                "category_code": category_code,
                "subcategory_code": subcategory_code,
            }
        )
    return promoted
