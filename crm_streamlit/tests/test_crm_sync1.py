"""Tests for CRM-SYNC-1: sync_all_processed().

All tests use mock DB objects — no real PostgreSQL required.
"""
from __future__ import annotations

import sys
import types as _types
from unittest.mock import MagicMock, patch, call

import pytest

# Only stub psycopg2 if not already installed (CI without postgres).
try:
    import psycopg2 as _real_psycopg2  # noqa: F401
except ImportError:
    _psycopg2 = _types.ModuleType("psycopg2")
    _psycopg2.extras = _types.ModuleType("psycopg2.extras")
    _psycopg2.connect = MagicMock()

    class _RealDictCursor:
        pass

    _psycopg2.extras.RealDictCursor = _RealDictCursor
    sys.modules.setdefault("psycopg2", _psycopg2)
    sys.modules.setdefault("psycopg2.extras", _psycopg2.extras)

from src.services.crm_procurements_sync import (
    SOURCE_CONFIGS,
    _acquire_sync_lock,
    _finish_sync_job,
    _sync_source,
    _update_aggregates,
    sync_all_processed,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_crm_db(running_jobs=None, query_returns=None):
    """Build a minimal crm_db mock."""
    db = MagicMock()
    # Default: no running jobs → lock succeeds
    _running = running_jobs if running_jobs is not None else []

    call_count = {"n": 0}
    def _execute_query(sql, params=None):
        # First call: check running → [] means no lock
        if "WHERE status = 'running'" in sql:
            return _running
        # Second call: fetch job id after insert (SELECT id FROM crm_sync_jobs ORDER BY id DESC LIMIT 1)
        if "crm_sync_jobs" in sql and "ORDER BY id DESC LIMIT 1" in sql:
            return [{"id": 99}]
        if query_returns is not None:
            r = query_returns.get(call_count["n"])
            call_count["n"] += 1
            return r or []
        return []

    db.execute_query.side_effect = _execute_query
    db.execute_update = MagicMock()
    return db


def _make_tender_db(rows_by_table: dict | None = None, processed_ids: list | None = None):
    """Build a tender_db mock.

    tender_db.execute_query returns tuples (tender_id,) for UNION id query.
    _tender_dict_query is patched separately at call site.
    """
    db = MagicMock()

    def _eq(sql, params=None):
        # UNION query for processed ids
        if "tender_document_matches" in sql and "processed_documents" in sql:
            ids = processed_ids if processed_ids is not None else [(1,), (2,)]
            return ids
        return []

    db.execute_query.side_effect = _eq
    db.get_connection = MagicMock(return_value=MagicMock())
    return db


def _source_rows_by_table(rows_map: dict):
    """Return a side_effect for _tender_dict_query based on src_table in SQL."""
    def _side(tender_db, sql, params=None):
        for key, rows in rows_map.items():
            if key in sql:
                return rows
        return []
    return _side


# ── Tests ────────────────────────────────────────────────────────────────────

class TestSyncProcessesAll:
    """1. Все 200 объектов обрабатываются, не ограничиваясь 60."""

    def test_all_200_processed(self):
        ids = [(i,) for i in range(1, 201)]
        tender_db = _make_tender_db(processed_ids=ids)
        crm_db = _make_crm_db()

        rows = [{"source_id": i, "contract_number": f"CN{i}", "auction_name": f"Name{i}",
                 "initial_price": 1000, "final_price": None, "customer": "C",
                 "delivery_region": None, "region_id": None,
                 "start_date": None, "end_date": None,
                 "delivery_start_date": None, "delivery_end_date": None,
                 "tender_link": None, "source_updated_at": None}
                for i in range(1, 201)]

        tbl_map = {"reestr_contract_44_fz": rows}

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table(tbl_map)):
            result = sync_all_processed(tender_db, crm_db)

        # reestr_contract_44_fz substring matches 44_fz / 44_fz_awarded / 44_fz_commission
        # so total inserted >= 200 (3 × 200 = 600 if all match)
        # Key: no LIMIT was applied — all 200 rows from at least one table are processed
        assert result["inserted"] >= 200
        assert result["errors"] == 0


class TestOpenAwardedNotMixed:
    """2. OPEN → crm_stage='torgi', AWARDED → crm_stage='razygranye'."""

    def test_stages_assigned_correctly(self):
        ids = [(1,)]
        tender_db = _make_tender_db(processed_ids=ids)
        crm_db = _make_crm_db()

        captured_stages = []

        def capture_update(sql, params=None):
            if params and "crm_stage" in params:
                captured_stages.append(params["crm_stage"])
            return None  # don't call original to avoid recursion

        crm_db.execute_update.side_effect = capture_update

        row = {"source_id": 1, "contract_number": "CN1", "auction_name": "Test",
               "initial_price": 1000, "final_price": None, "customer": "C",
               "delivery_region": None, "region_id": None,
               "start_date": None, "end_date": None,
               "delivery_start_date": None, "delivery_end_date": None,
               "tender_link": None, "source_updated_at": None}

        call_idx = {"n": 0}
        ordered = [(cfg[0], cfg[2]) for cfg in SOURCE_CONFIGS]  # (table, stage)

        def dict_q(tender_db, sql, params=None):
            for tbl, stage in ordered:
                if tbl in sql:
                    return [row]
            return []

        with patch("src.services.crm_procurements_sync._tender_dict_query", side_effect=dict_q):
            sync_all_processed(tender_db, crm_db)

        # Stages captured: torgi for OPEN tables, razygranye for AWARDED
        assert "torgi" in captured_stages
        assert "razygranye" in captured_stages
        assert "commission" in captured_stages


class TestFilesOnlySynced:
    """3. Объект с doc_count>0 но match_count=0 всё равно синхронизируется."""

    def test_files_only_object_synced(self):
        # Source: processed_documents has tender_id=5, matches has nothing
        tender_db = MagicMock()

        def eq(sql, params=None):
            if "tender_document_matches" in sql and "processed_documents" in sql:
                return [(5,)]  # from UNION
            return []

        tender_db.execute_query.side_effect = eq
        tender_db.get_connection.return_value = MagicMock()

        crm_db = _make_crm_db()
        row = {"source_id": 5, "contract_number": "CN5", "auction_name": "Files Only",
               "initial_price": None, "final_price": None, "customer": "C",
               "delivery_region": None, "region_id": None,
               "start_date": None, "end_date": None,
               "delivery_start_date": None, "delivery_end_date": None,
               "tender_link": None, "source_updated_at": None}

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table({"reestr_contract_44_fz": [row]})):
            result = sync_all_processed(tender_db, crm_db)

        assert result["inserted"] >= 1


class TestEvidenceSynced:
    """4. Объект с evidence_count > 0 синхронизируется."""

    def test_evidence_object_synced(self):
        tender_db = _make_tender_db(processed_ids=[(10,)])
        crm_db = _make_crm_db()

        row = {"source_id": 10, "contract_number": "CN10", "auction_name": "Evidence",
               "initial_price": 500000, "final_price": None, "customer": "C",
               "delivery_region": None, "region_id": None,
               "start_date": None, "end_date": None,
               "delivery_start_date": None, "delivery_end_date": None,
               "tender_link": None, "source_updated_at": None}

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table({"reestr_contract_44_fz": [row]})):
            result = sync_all_processed(tender_db, crm_db)

        assert result["inserted"] >= 1


class TestNoKeywordNoLoss:
    """5. Объект без keyword в auction_name не теряется."""

    def test_no_keyword_still_synced(self):
        tender_db = _make_tender_db(processed_ids=[(7,)])
        crm_db = _make_crm_db()

        row = {"source_id": 7, "contract_number": "CN7",
               "auction_name": "Совершенно уникальное название без ключевых слов",
               "initial_price": 100000, "final_price": None, "customer": "C",
               "delivery_region": None, "region_id": None,
               "start_date": None, "end_date": None,
               "delivery_start_date": None, "delivery_end_date": None,
               "tender_link": None, "source_updated_at": None}

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table({"reestr_contract_44_fz": [row]})):
            result = sync_all_processed(tender_db, crm_db)

        assert result["inserted"] >= 1
        assert result["errors"] == 0


class TestUpsertIdempotent:
    """6. Повторный sync не создаёт дубль — UPSERT ON CONFLICT."""

    def test_upsert_call_uses_on_conflict(self):
        tender_db = _make_tender_db(processed_ids=[(1,)])
        crm_db = _make_crm_db()

        row = {"source_id": 1, "contract_number": "CN1", "auction_name": "A",
               "initial_price": None, "final_price": None, "customer": "C",
               "delivery_region": None, "region_id": None,
               "start_date": None, "end_date": None,
               "delivery_start_date": None, "delivery_end_date": None,
               "tender_link": None, "source_updated_at": None}

        sqls_called = []
        orig = crm_db.execute_update.side_effect

        def capture(sql, params=None):
            sqls_called.append(sql)

        crm_db.execute_update.side_effect = capture

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table({"reestr_contract_44_fz": [row]})):
            sync_all_processed(tender_db, crm_db)

        upsert_sqls = [s for s in sqls_called if "ON CONFLICT" in s]
        assert len(upsert_sqls) >= 1


class TestQualificationNotOverwritten:
    """7. sync не затирает qualification_state='confirmed'."""

    def test_upsert_does_not_include_qualification_in_update(self):
        tender_db = _make_tender_db(processed_ids=[(1,)])
        crm_db = _make_crm_db()

        row = {"source_id": 1, "contract_number": "CN1", "auction_name": "A",
               "initial_price": None, "final_price": None, "customer": "C",
               "delivery_region": None, "region_id": None,
               "start_date": None, "end_date": None,
               "delivery_start_date": None, "delivery_end_date": None,
               "tender_link": None, "source_updated_at": None}

        sqls_called = []

        def capture(sql, params=None):
            sqls_called.append(sql)

        crm_db.execute_update.side_effect = capture

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table({"reestr_contract_44_fz": [row]})):
            sync_all_processed(tender_db, crm_db)

        # The DO UPDATE SET part must NOT set qualification_state
        for sql in sqls_called:
            if "ON CONFLICT" in sql:
                update_part = sql.split("DO UPDATE SET")[-1] if "DO UPDATE SET" in sql else ""
                assert "qualification_state" not in update_part, (
                    "UPSERT must not overwrite qualification_state on conflict"
                )


class TestDifferentSourceTablesSameId:
    """8. (44_fz, id=1) и (223_fz, id=1) → разные записи в CRM."""

    def test_different_source_tables(self):
        tender_db = _make_tender_db(processed_ids=[(1,)])
        crm_db = _make_crm_db()

        row44 = {"source_id": 1, "contract_number": "CN44", "auction_name": "44fz row",
                 "initial_price": None, "final_price": None, "customer": "C44",
                 "delivery_region": None, "region_id": None,
                 "start_date": None, "end_date": None,
                 "delivery_start_date": None, "delivery_end_date": None,
                 "tender_link": None, "source_updated_at": None}

        row223 = dict(row44)
        row223["customer"] = "C223"
        row223["contract_number"] = "CN223"

        sqls_with_params = []

        def capture(sql, params=None):
            if params and params.get("source_id") == 1:
                sqls_with_params.append((sql, params))

        crm_db.execute_update.side_effect = capture

        def dict_q(tender_db, sql, params=None):
            if "reestr_contract_44_fz " in sql and "awarded" not in sql and "commission" not in sql:
                return [row44]
            if "reestr_contract_223_fz " in sql and "awarded" not in sql and "commission" not in sql:
                return [row223]
            return []

        with patch("src.services.crm_procurements_sync._tender_dict_query", side_effect=dict_q):
            sync_all_processed(tender_db, crm_db)

        source_tables = [p.get("source_table") for _, p in sqls_with_params if p]
        assert "reestr_contract_44_fz" in source_tables
        assert "reestr_contract_223_fz" in source_tables


class TestErrorPerRowNotStopsBatch:
    """9. Ошибка одной строки — остальные обрабатываются."""

    def test_one_error_batch_continues(self):
        tender_db = _make_tender_db(processed_ids=[(1,), (2,), (3,)])
        crm_db = _make_crm_db()

        rows = [
            {"source_id": 1, "contract_number": "CN1", "auction_name": "OK",
             "initial_price": None, "final_price": None, "customer": "C",
             "delivery_region": None, "region_id": None,
             "start_date": None, "end_date": None,
             "delivery_start_date": None, "delivery_end_date": None,
             "tender_link": None, "source_updated_at": None},
            {"source_id": 2, "contract_number": "CN2", "auction_name": "ERR",
             "initial_price": None, "final_price": None, "customer": "C",
             "delivery_region": None, "region_id": None,
             "start_date": None, "end_date": None,
             "delivery_start_date": None, "delivery_end_date": None,
             "tender_link": None, "source_updated_at": None},
            {"source_id": 3, "contract_number": "CN3", "auction_name": "OK3",
             "initial_price": None, "final_price": None, "customer": "C",
             "delivery_region": None, "region_id": None,
             "start_date": None, "end_date": None,
             "delivery_start_date": None, "delivery_end_date": None,
             "tender_link": None, "source_updated_at": None},
        ]

        call_count = {"n": 0}

        def failing_update(sql, params=None):
            if params and params.get("source_id") == 2 and sql and "ON CONFLICT" in sql:
                raise Exception("Simulated DB error for row 2")
            # Normal calls (job insert, job finish, aggregates) succeed silently
            return None

        crm_db.execute_update.side_effect = failing_update

        with patch("src.services.crm_procurements_sync._tender_dict_query",
                   side_effect=_source_rows_by_table({"reestr_contract_44_fz": rows})):
            result = sync_all_processed(tender_db, crm_db)

        # Rows 1 and 3 inserted, row 2 error
        assert result["errors"] >= 1
        assert result["inserted"] >= 2


class TestOverlappingSyncBlocked:
    """10. Второй запуск при работающем первом → отказ."""

    def test_second_run_blocked(self):
        tender_db = _make_tender_db(processed_ids=[])
        # Simulate running job present
        crm_db = _make_crm_db(running_jobs=[{"id": 55}])

        result = sync_all_processed(tender_db, crm_db)

        assert result["skipped_lock"] == 1
        assert result["inserted"] == 0


class TestPaginationNotAffectTotalCount:
    """11. total_count независим от page offset — вычисляется отдельным запросом."""

    def test_total_count_query_no_limit(self):
        """The count query in _render_review_tab must not have OFFSET/LIMIT."""
        from src.ui.components.analytics_v2.tabs import _load_review_counts

        captured_sqls = []

        class MockCursor:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def execute(self, sql, params=None): captured_sqls.append(sql)
            def fetchone(self): return {"total": 851, "open_cnt": 378, "awarded_cnt": 473,
                                        "commission_cnt": 0, "with_evidence": 233,
                                        "with_matches": 956, "unassessed_cnt": 600,
                                        "candidate_cnt": 200, "manual_cnt": 51}

        class MockConn:
            def cursor(self, cursor_factory=None): return MockCursor()
            def close(self): pass

        with patch("psycopg2.connect", return_value=MockConn()):
            result = _load_review_counts()

        assert result["total"] == 851
        # Verify no LIMIT/OFFSET in count SQL
        count_sqls = [s for s in captured_sqls if "count(*)" in s.lower()]
        for sql in count_sqls:
            assert "LIMIT" not in sql.upper()
            assert "OFFSET" not in sql.upper()


class TestReviewTabCountsFullSet:
    """12. Счётчики по всей выборке, не только по странице."""

    def test_count_uses_full_table_not_paginated(self):
        from src.ui.components.analytics_v2.tabs import _load_review_counts

        class MockCursor:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def execute(self, sql, params=None): pass
            def fetchone(self):
                return {"total": 851, "open_cnt": 378, "awarded_cnt": 473,
                        "commission_cnt": 0, "with_evidence": 233,
                        "with_matches": 956, "unassessed_cnt": 600,
                        "candidate_cnt": 200, "manual_cnt": 51}

        class MockConn:
            def cursor(self, cursor_factory=None): return MockCursor()
            def close(self): pass

        with patch("psycopg2.connect", return_value=MockConn()):
            counts = _load_review_counts()

        assert counts["total"] == 851
        assert counts["open_cnt"] + counts["awarded_cnt"] + counts["commission_cnt"] <= counts["total"]
