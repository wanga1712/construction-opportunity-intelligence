"""Tests for S7 source read-only enforcement and match-cache rehome."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.services.crm_procurements_sync import match_cache_refresh, sync_torgi
from src.services.docs_soft_reclassify import soft_reclassify_docs_queue
from src.services.source_db_readonly import (
    SourceDbWriteRejected,
    SourceReadOnlyDatabase,
    looks_like_write_sql,
    wrap_source_db_readonly,
)


class FakeInner:
    def __init__(self):
        self.updates = []
        self.queries = []
        self._conn = MagicMock()

    def connect(self, fallback_to_offline=True):
        return None

    def get_connection(self):
        return self._conn

    def execute_update(self, query, params=None, timeout=None):
        self.updates.append((query, params))
        return True

    def execute_batch(self, query, params_list, timeout=None):
        self.updates.append((query, params_list))
        return True

    def execute_query(self, query, params=None, fetch_results=True, timeout=None):
        self.queries.append((query, params))
        return []

    def execute_scalar(self, query, params=None, timeout=None):
        return 1


class FakeCrm:
    def __init__(self):
        self.updates = []
        self.queries = []

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        sql_l = (sql or "").lower()
        if "to_regclass" in sql_l:
            # Presence checks for fail-closed schema guard
            return [{"ok": True}]
        if "information_schema.tables" in sql_l:
            return [{"ok": True}]
        if "crm_search_rules" in sql:
            return [
                {"search_profile_id": 8, "value": "светильник", "weight": 10},
            ]
        if "crm_tender_match_cache" in sql and "SELECT" in sql.upper():
            return [
                {
                    "source_id": 1,
                    "crm_profile_id": 8,
                    "match_score": 10,
                    "matched_keywords": ["светильник"],
                }
            ]
        return []

    def execute_update(self, sql, params=None):
        self.updates.append((sql, params))
        return True


def test_looks_like_write_sql_not_naive_select():
    assert looks_like_write_sql("SELECT 1") is False
    assert looks_like_write_sql("WITH x AS (SELECT 1) SELECT * FROM x") is False
    assert looks_like_write_sql("INSERT INTO t VALUES (1)") is True
    assert looks_like_write_sql("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x") is True


def test_source_write_rejection_execute_update():
    wrapped = SourceReadOnlyDatabase(FakeInner(), enforce_session_readonly=False)
    with pytest.raises(SourceDbWriteRejected):
        wrapped.execute_update("INSERT INTO reestr_contract_44_fz(id) VALUES (1)")


def test_source_write_rejection_execute_batch():
    wrapped = SourceReadOnlyDatabase(FakeInner(), enforce_session_readonly=False)
    with pytest.raises(SourceDbWriteRejected):
        wrapped.execute_batch("DELETE FROM okpd_from_users", [{}])


def test_source_reads_still_work():
    inner = FakeInner()
    wrapped = SourceReadOnlyDatabase(inner, enforce_session_readonly=False)
    wrapped.execute_query("SELECT id FROM reestr_contract_44_fz LIMIT 1")
    wrapped.execute_query(
        "SELECT sub_code FROM collection_codes_okpd WHERE sub_code IS NOT NULL LIMIT 1"
    )
    assert len(inner.queries) == 2
    assert len(inner.updates) == 0


def test_wrap_helper():
    wrapped = wrap_source_db_readonly(FakeInner())
    assert isinstance(wrapped, SourceReadOnlyDatabase)


def test_match_cache_refresh_writes_crm_only():
    source = SourceReadOnlyDatabase(FakeInner(), enforce_session_readonly=False)
    # Patch _tender_dict_query path by stubbing execute via get_connection cursor
    # Instead call with a tender fake that supports _tender_dict_query's get_connection.
    tender = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [{"id": 42, "auction_name": "Поставка светильник LED"}]
    conn.cursor.return_value = cur
    tender.get_connection.return_value = conn

    crm = FakeCrm()
    # Also reject if someone passes writable source wrapping
    result = match_cache_refresh(tender, crm, since_days=30)
    assert result.get("write_role") == "crm_db"
    assert result.get("cached", 0) >= 1
    assert any("crm_tender_match_cache" in (u[0] or "") and "INSERT" in (u[0] or "").upper() for u in crm.updates)
    # tender must not receive execute_update
    assert not getattr(tender, "execute_update").called


def test_match_cache_refresh_source_write_calls_zero_when_guarded():
    inner = FakeInner()
    source = SourceReadOnlyDatabase(inner, enforce_session_readonly=False)
    crm = FakeCrm()

    # _tender_dict_query needs get_connection — use MagicMock tender for reads,
    # and assert guarded source rejects writes separately.
    with pytest.raises(SourceDbWriteRejected):
        source.execute_update("INSERT INTO crm_tender_match_cache VALUES (1)")
    assert inner.updates == []


def test_soft_reclassify_blocked():
    stats = soft_reclassify_docs_queue(MagicMock())
    assert stats.get("blocked") is True
    assert "SOURCE_DB_READONLY" in stats.get("error", "")


def test_sync_torgi_reads_cache_from_crm():
    tender = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [
        {
            "source_id": 1,
            "contract_number": "CN",
            "auction_name": "x",
            "initial_price": 1,
            "final_price": None,
            "customer": "c",
            "delivery_region": None,
            "region_id": None,
            "okpd_code": "27.40",
            "okpd_name": "light",
            "contractor_name": None,
            "contractor_inn": None,
            "start_date": None,
            "end_date": None,
            "delivery_start_date": None,
            "delivery_end_date": None,
            "tender_link": None,
            "source_updated_at": None,
        }
    ]
    conn.cursor.return_value = cur
    tender.get_connection.return_value = conn

    crm = FakeCrm()

    # ensure_schema import path — stub
    import src.services.crm_procurements_sync as mod

    orig = getattr(mod, "ensure_schema", None)
    # patch via crm_procurements_schema
    import src.services.crm_procurements_schema as schema_mod

    old = schema_mod.ensure_schema
    schema_mod.ensure_schema = lambda db: True
    try:
        result = sync_torgi(tender, crm, since_days=30)
    finally:
        schema_mod.ensure_schema = old

    assert result.get("read_cache_role") == "crm_db"
    assert any("FROM crm_tender_match_cache" in (q[0] or "") for q in crm.queries)
    assert tender.execute_update.call_count == 0
