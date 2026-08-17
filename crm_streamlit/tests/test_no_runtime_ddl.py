"""Assert CRM runtime helpers do not execute DDL."""
from __future__ import annotations

import pytest

from src.services.crm_procurements_schema import ensure_schema
from src.services.docs_priority_sync import sync_docs_priority_hints
from src.services.schema_guard import SchemaNotReady, require_relations_or_raise
from src.services.source_db_readonly import ensure_match_cache_table


class FakeCrm:
    def __init__(self, existing=None):
        self.existing = set(existing or [])
        self.updates = []

    def execute_query(self, sql, params=None, fetch_results=True, timeout=None):
        name = None
        if isinstance(params, dict) and "fqn" in params:
            name = str(params["fqn"]).split(".")[-1]
        elif isinstance(params, (list, tuple)) and params:
            # to_regclass(%s) or information_schema (schema, table)
            if len(params) >= 2 and "information_schema" in (sql or "").lower():
                name = str(params[1])
            else:
                name = str(params[0]).split(".")[-1]
        return [{"ok": bool(name and name in self.existing)}]

    def execute_update(self, sql, params=None, timeout=None):
        self.updates.append(sql)
        return True

    def is_offline_mode(self):
        return False


def test_docs_priority_fail_closed_no_ddl():
    crm = FakeCrm(existing=[])
    res = sync_docs_priority_hints(crm, [])
    assert res.get("status") == "NOT_READY"
    assert crm.updates == []


def test_match_cache_require_no_ddl():
    crm = FakeCrm(existing=[])
    with pytest.raises(SchemaNotReady):
        ensure_match_cache_table(crm)
    assert crm.updates == []


def test_procurements_schema_check_only():
    crm = FakeCrm(
        existing=["crm_procurements", "crm_sync_jobs", "crm_sync_events", "crm_settings"]
    )
    assert ensure_schema(crm) is True
    assert crm.updates == []
    crm2 = FakeCrm(existing=[])
    assert ensure_schema(crm2) is False
    assert crm2.updates == []


def test_require_relations_or_raise():
    crm = FakeCrm(existing=["crm_tender_match_cache"])
    require_relations_or_raise(crm, ["crm_tender_match_cache"])
    with pytest.raises(SchemaNotReady):
        require_relations_or_raise(crm, ["missing_table"])
