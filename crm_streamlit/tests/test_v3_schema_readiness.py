from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

import pytest

from src.services.commercial_routing_v3.schema_readiness import (
    V3SchemaReadiness,
    check_v3_schema_readiness,
    decide_v3_runtime_execution_allowed,
)


class FakeCrmDb:
    """
    Minimal fake for readiness checks.

    Schema is expressed as:
      tables = {table_name: {col1, col2, ...}}
    for schema=public only.
    """

    def __init__(self, tables: Dict[str, Set[str]]):
        self._tables = tables

    def execute_scalar(self, sql: str, params: Optional[Any] = None) -> Any:
        if "to_regclass" in sql:
            # sql example: SELECT to_regclass('public.crm_x') IS NOT NULL
            # We'll parse substring between to_regclass('...') and ')
            import re

            m = re.search(r"to_regclass\('([^']+)'\)", sql)
            if not m:
                return None
            fqn = m.group(1)  # public.table
            table = fqn.split(".", 1)[1] if "." in fqn else fqn
            return (1 if table in self._tables else None)
        raise AssertionError(f"Unexpected execute_scalar SQL: {sql[:120]}")

    def execute_query(self, sql: str, params: Optional[Any] = None) -> List[Any]:
        if "information_schema.columns" in sql:
            schema, table_name, column_name = params
            if schema != "public":
                return []
            cols = self._tables.get(table_name, set())
            return [1] if column_name in cols else []
        raise AssertionError(f"Unexpected execute_query SQL: {sql[:120]}")


def test_v3_readiness_missing_tables() -> None:
    db = FakeCrmDb(
        tables={
            # only some tables exist
            "crm_product_categories": {
                "category_code",
                "category_name",
                "description",
                "is_active",
                "sort_order",
                "semantic_type",
                "lifecycle_state",
                "searchability_mode",
            }
        }
    )
    r = check_v3_schema_readiness(db)
    assert isinstance(r, V3SchemaReadiness)
    assert r.ready is False
    assert any(m.startswith("missing_table:") for m in r.missing)
    assert r.legacy_registry_readable is True
    assert r.live_registry_v3_schema_ready is False


def test_v3_readiness_legacy_registry_readable_but_semantic_missing() -> None:
    db = FakeCrmDb(
        tables={
            "crm_category_okpd_priors": {"id", "commercial_category_code"},
            "crm_category_routing_signals": {"id", "commercial_category_code"},
            "crm_procurement_category_opportunities": {
                "id",
                "procurement_id",
                "commercial_state",
                "last_source_event",
                "last_source_seen_at",
                "source_missing_since",
                "source_sync_status",
                "opportunity_track",
                "commercial_priority_score",
                "research_value_score",
            },
            "crm_category_opportunity_lifecycle_audit": {"id", "procurement_id"},
            "crm_product_categories": {
                "category_code",
                "category_name",
                "description",
                "is_active",
                "sort_order",
                # semantic columns are missing intentionally
            },
        }
    )
    r = check_v3_schema_readiness(db)
    assert r.ready is False
    assert r.legacy_registry_readable is True
    assert r.live_registry_v3_schema_ready is False
    assert any("missing_column:crm_product_categories.semantic_type" in m for m in r.missing)


def test_v3_readiness_ready() -> None:
    db = FakeCrmDb(
        tables={
            "crm_category_okpd_priors": {"id", "commercial_category_code"},
            "crm_category_routing_signals": {"id", "commercial_category_code"},
            "crm_procurement_category_opportunities": {
                "id",
                "procurement_id",
                "commercial_state",
                "last_source_event",
                "last_source_seen_at",
                "source_missing_since",
                "source_sync_status",
                "opportunity_track",
                "commercial_priority_score",
                "research_value_score",
                "commercial_category_code",
                "commercial_subcategory_code",
            },
            "crm_category_opportunity_lifecycle_audit": {
                "id",
                "procurement_id",
                "opportunity_id",
            },
            "crm_legacy_okpd_migration_audit": {
                "id",
                "source_table",
                "classification",
            },
            "crm_product_categories": {
                "category_code",
                "category_name",
                "description",
                "is_active",
                "sort_order",
                "semantic_type",
                "lifecycle_state",
                "searchability_mode",
            },
        }
    )
    r = check_v3_schema_readiness(db)
    assert r.ready is True
    assert r.missing == []
    assert r.legacy_registry_readable is True
    assert r.live_registry_v3_schema_ready is True


def test_v3_runtime_execution_decision_fail_closed() -> None:
    readiness = V3SchemaReadiness(
        ready=False,
        missing=["missing_table:public.crm_category_okpd_priors"],
        legacy_registry_readable=True,
        live_registry_v3_schema_ready=False,
        missing_details={},
    )
    allowed, reason = decide_v3_runtime_execution_allowed(
        feature_flag_enabled=True, readiness=readiness
    )
    assert allowed is False
    assert reason == "schema_not_ready"

