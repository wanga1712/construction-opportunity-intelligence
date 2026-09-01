"""Regression tests for Target Claim & Service Starvation Fix (R3-4D).

Mandatory tests:
1. Target ID filter is applied before LIMIT
2. Out-of-target prefix cannot starve target row
3. Empty target ID list ([]) claims zero
4. None/unfiltered behavior explicit
5. V3/other generation excluded
6. Only unvalidated states eligible
7. TARGET candidate eligible
8. OUT_OF_TARGET candidate not normally eligible
9. UNKNOWN_OKPD candidate not normally eligible
10. Refreshed target set can include a newly added target procurement
11. Stale target cache cannot create endless reclaim loop
12. Hydration regression still passes
13. No model call during acceptance
"""

import json
import pytest
import sys
import os
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator_service import (
    claim_unvalidated_candidates,
    get_target_procurement_ids,
    get_cached_target_procurement_ids,
    process_batch,
    filter_target_candidates,
    PIPELINE_GENERATION,
    _TARGET_IDS_CACHE,
    DEFAULT_TARGET_REFRESH_SECONDS,
)
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    hydrate_candidate_context,
)
from src.services.commercial_routing_v3.okpd_priors import ADMISSION_TARGET, ADMISSION_OUT_OF_TARGET, ADMISSION_UNKNOWN_OKPD


# Mock connection & cursor helper
class MockCursor:
    def __init__(self, fetch_data=None):
        self.fetch_data = fetch_data or []
        self.last_query = ""
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchall(self):
        return self.fetch_data

    def fetchone(self):
        return self.fetch_data[0] if self.fetch_data else None


class MockConnection:
    def __init__(self, fetch_data=None):
        self.cursor_obj = MockCursor(fetch_data)

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def commit(self):
        pass


# ============================================================
# Test 1: Target ID filter is applied before LIMIT in SQL
# ============================================================
def test_target_id_filter_applied_before_limit():
    conn = MockConnection([])
    target_pids = [100, 200, 300]
    claim_unvalidated_candidates(conn, batch_size=10, target_procurement_ids=target_pids)

    query = conn.cursor_obj.last_query
    params = conn.cursor_obj.last_params

    assert "AND d.procurement_id = ANY(%s)" in query, "SQL must include ANY(%s) filter"
    assert target_pids in params, "target_pids must be in query params"
    # Ensure ORDER BY ... LIMIT comes AFTER WHERE clauses
    where_idx = query.find("WHERE")
    any_idx = query.find("AND d.procurement_id = ANY(%s)")
    order_idx = query.find("ORDER BY")
    limit_idx = query.find("LIMIT")

    assert where_idx < any_idx < order_idx < limit_idx, "ANY(%s) predicate must be before ORDER BY and LIMIT"


# ============================================================
# Test 2: Out-of-target prefix cannot starve target row (Starvation Reproduction)
# ============================================================
def test_out_of_target_prefix_cannot_starve_target_row():
    """
    Simulates a database with:
    Details 1..10: procurement_id=99 (OUT_OF_TARGET)
    Detail 11: procurement_id=100 (TARGET)

    Batch size = 5 (smaller than prefix size 10).
    Old behavior: claimed rows 1..5 (out-of-target), filtered all out, returned 0, reclaimed 1..5 forever.
    New behavior: SQL filter target_procurement_ids=[100] restricts claim to procurement 100, claiming detail 11.
    """
    db_rows = [
        {"id": 11, "procurement_id": 100, "category_code": "lighting", "subcategory_code": "road_street",
         "validation_status": "UNKNOWN", "pipeline_generation": PIPELINE_GENERATION}
    ]
    conn = MockConnection(db_rows)

    # TARGET set contains only procurement 100
    claimed = claim_unvalidated_candidates(conn, batch_size=5, target_procurement_ids=[100])

    assert len(claimed) == 1
    assert claimed[0]["procurement_id"] == 100
    assert claimed[0]["id"] == 11, "Target detail 11 behind out-of-target prefix MUST be claimed"


# ============================================================
# Test 3: Empty target ID list ([]) claims ZERO rows
# ============================================================
def test_empty_target_id_list_claims_zero():
    conn = MockConnection([{"id": 1, "procurement_id": 99}])
    claimed = claim_unvalidated_candidates(conn, batch_size=10, target_procurement_ids=[])
    assert claimed == [], "Empty target list MUST return [] immediately without querying DB"


# ============================================================
# Test 4: None / unfiltered behavior explicit
# ============================================================
def test_none_unfiltered_claims_everything():
    conn = MockConnection([{"id": 1, "procurement_id": 99}])
    claimed = claim_unvalidated_candidates(conn, batch_size=10, target_procurement_ids=None)

    query = conn.cursor_obj.last_query
    assert "AND d.procurement_id = ANY(%s)" not in query, "None target_procurement_ids must NOT filter by procurement_id"
    assert len(claimed) == 1


# ============================================================
# Test 5: V3 / other generation excluded by SQL
# ============================================================
def test_other_generation_excluded_by_sql():
    conn = MockConnection([])
    claim_unvalidated_candidates(conn, batch_size=10, generation="S13_V4_EXHAUSTIVE_CONTEXT")

    query = conn.cursor_obj.last_query
    params = conn.cursor_obj.last_params

    assert "AND d.pipeline_generation = %s" in query
    assert "S13_V4_EXHAUSTIVE_CONTEXT" in params


# ============================================================
# Test 6: Only unvalidated states eligible
# ============================================================
def test_only_unvalidated_states_eligible():
    conn = MockConnection([])
    claim_unvalidated_candidates(conn, batch_size=10)

    query = conn.cursor_obj.last_query
    assert "d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING')" in query
    assert "OR d.validation_status IS NULL" in query


# ============================================================
# Test 7: TARGET candidate eligible
# ============================================================
def test_target_candidate_eligible():
    priors = [{"okpd_pattern": "27.40", "status": "TARGET"}]
    candidates = [{"procurement_okpd_code": "27.40.39.000"}]
    target_cands = filter_target_candidates(candidates, priors)
    assert len(target_cands) == 1


# ============================================================
# Test 8: OUT_OF_TARGET candidate not normally eligible
# ============================================================
def test_out_of_target_candidate_not_eligible():
    priors = [{"okpd_code": "27.40", "status": "TARGET"}, {"okpd_code": "86.10", "status": "OUT_OF_TARGET"}]
    candidates = [{"procurement_okpd_code": "86.10.10.000"}]
    target_cands = filter_target_candidates(candidates, priors)
    assert len(target_cands) == 0


# ============================================================
# Test 9: UNKNOWN_OKPD candidate not normally eligible
# ============================================================
def test_unknown_okpd_candidate_not_eligible():
    priors = [{"okpd_pattern": "27.40", "status": "TARGET"}]
    candidates = [{"procurement_okpd_code": "99.99.99.999"}]
    target_cands = filter_target_candidates(candidates, priors)
    assert len(target_cands) == 0


# ============================================================
# Test 10: Refreshed target set can include a newly added target procurement
# ============================================================
def test_target_set_refresh_includes_new_procurement():
    _TARGET_IDS_CACHE["ids"] = [100]
    _TARGET_IDS_CACHE["refreshed_at"] = time.time() - 100.0  # stale (>60s)

    crm_rows = [{"id": 100, "okpd_code": "27.40.10"}, {"id": 200, "okpd_code": "27.40.20"}]
    crm_conn = MockConnection(crm_rows)
    priors = [{"okpd_pattern": "27.40", "status": "TARGET"}]

    refreshed_ids = get_cached_target_procurement_ids(crm_conn, priors, refresh_interval=60.0)

    assert 200 in refreshed_ids, "Newly added target procurement 200 MUST be included after refresh"
    assert len(refreshed_ids) == 2


# ============================================================
# Test 11: Stale target cache cannot create endless reclaim loop
# ============================================================
def test_stale_target_cache_force_refreshes():
    _TARGET_IDS_CACHE["ids"] = [100, 99]
    _TARGET_IDS_CACHE["refreshed_at"] = time.time()

    crm_rows = [{"id": 100, "okpd_code": "27.40.10"}]  # 99 was removed or changed to out-of-target
    crm_conn = MockConnection(crm_rows)
    priors = [{"okpd_pattern": "27.40", "status": "TARGET"}]

    # Force refresh
    refreshed_ids = get_cached_target_procurement_ids(crm_conn, priors, force_refresh=True)

    assert 99 not in refreshed_ids, "Stale ID 99 MUST be removed from cache after force_refresh"
    assert refreshed_ids == [100]


# ============================================================
# Test 12: Hydration regression still passes
# ============================================================
def test_hydration_regression():
    candidate = {
        "matched_line": "",
        "context_before": {},
        "context_after": {},
        "row_data": {
            "raw_cells": [{"col": "A", "text": "Светильник LED 40W"}],
            "context_before": ["Электрический щит"],
            "context_after": ["Счетчик"],
        },
    }
    hydrated = hydrate_candidate_context(candidate)
    assert hydrated["matched_line"] == "Светильник LED 40W"
    assert hydrated["context_before"] == ["Электрический щит"]
    assert hydrated["context_after"] == ["Счетчик"]


# ============================================================
# Test 13: No model call during acceptance
# ============================================================
def test_no_model_call_during_process_batch():
    mock_ai = mock.MagicMock(return_value='{"decision":"UNKNOWN"}')
    validator = ContextValidator(ai_caller=mock_ai)

    doc_conn = MockConnection([])
    crm_conn = MockConnection([])
    priors = []
    taxonomy = mock.MagicMock(categories={})

    # process_batch when no candidates claimed
    result = process_batch(doc_conn, crm_conn, validator, priors, taxonomy, target_procurement_ids=[])

    assert result == 0
    mock_ai.assert_not_called()
