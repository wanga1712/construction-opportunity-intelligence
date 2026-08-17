from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class V3SchemaReadiness:
    ready: bool
    missing: List[str]
    legacy_registry_readable: bool
    live_registry_v3_schema_ready: bool
    missing_details: Dict[str, Any]


def _table_exists(crm_db, table_fqn: str) -> bool:
    """
    Fast existence check without relying on schema.table layout.
    table_fqn example: public.crm_procurement_category_opportunities
    """
    try:
        return bool(
            crm_db.execute_scalar(f"SELECT to_regclass('{table_fqn}') IS NOT NULL")
        )
    except Exception:
        return False


def _column_exists(crm_db, table_name: str, column_name: str, schema: str = "public") -> bool:
    sql = """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
    """
    try:
        rows = crm_db.execute_query(sql, (schema, table_name, column_name))
        return bool(rows)
    except Exception:
        return False


def check_v3_schema_readiness(crm_db) -> V3SchemaReadiness:
    required_tables = [
        "public.crm_category_okpd_priors",
        "public.crm_category_routing_signals",
        "public.crm_procurement_category_opportunities",
        "public.crm_category_opportunity_lifecycle_audit",
        "public.crm_legacy_okpd_migration_audit",
    ]

    missing: List[str] = []
    missing_details: Dict[str, Any] = {}

    for t in required_tables:
        if not _table_exists(crm_db, t):
            missing.append(f"missing_table:{t}")

    # Semantic registry columns in crm_product_categories (required for V3 live registry).
    required_semantic_columns = [
        ("crm_product_categories", "semantic_type"),
        ("crm_product_categories", "lifecycle_state"),
        ("crm_product_categories", "searchability_mode"),
    ]

    # Determine "legacy readable" (table exists + legacy-safe columns exist).
    legacy_readable = True
    try:
        for col in ("category_code", "category_name", "description", "is_active", "sort_order"):
            if not _column_exists(crm_db, "crm_product_categories", col):
                legacy_readable = False
                missing_details["legacy_missing_column"] = col
                break
    except Exception:
        legacy_readable = False

    live_v3_ready = True
    for table_name, col in required_semantic_columns:
        if not _column_exists(crm_db, table_name, col):
            live_v3_ready = False
            missing.append(f"missing_column:{table_name}.{col}")

    # Required opportunity lifecycle columns.
    required_opp_cols = [
        ("crm_procurement_category_opportunities", "commercial_state"),
        ("crm_procurement_category_opportunities", "last_source_event"),
        ("crm_procurement_category_opportunities", "last_source_seen_at"),
        ("crm_procurement_category_opportunities", "source_missing_since"),
        ("crm_procurement_category_opportunities", "source_sync_status"),
        ("crm_procurement_category_opportunities", "opportunity_track"),
        ("crm_procurement_category_opportunities", "commercial_priority_score"),
        ("crm_procurement_category_opportunities", "research_value_score"),
    ]
    for table_name, col in required_opp_cols:
        if not _column_exists(crm_db, table_name, col):
            live_v3_ready = False
            missing.append(f"missing_column:{table_name}.{col}")

    ready = len(missing) == 0
    return V3SchemaReadiness(
        ready=ready,
        missing=missing,
        legacy_registry_readable=legacy_readable,
        live_registry_v3_schema_ready=live_v3_ready,
        missing_details=missing_details,
    )


def decide_v3_runtime_execution_allowed(
    *, feature_flag_enabled: bool, readiness: V3SchemaReadiness
) -> tuple[bool, str]:
    """
    Fail-closed decision:
    - if feature flag disabled -> not allowed
    - if schema readiness is false -> not allowed (no silent V2 semantics under V3 name)
    """
    if not feature_flag_enabled:
        return False, "feature_disabled"
    if readiness.ready:
        return True, "ready"
    return False, "schema_not_ready"

