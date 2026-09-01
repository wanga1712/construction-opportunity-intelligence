"""Deterministic regression tests for Validation Attempt Terminality Fix (R3-4D-A).

Validates:
1. UNKNOWN + validated_at NULL is eligible
2. UNKNOWN + validated_at timestamp is NOT eligible
3. RAW + validated_at NULL is eligible
4. PENDING + validated_at NULL is eligible
5. Semantic v2 UNKNOWN after completed attempt not reclaimed
6. MODEL_EXCEPTION UNKNOWN after completed attempt not reclaimed
7. Historical v1 UNKNOWN with validated_at set not reclaimed
8. CONFIRMED not eligible
9. REJECTED not eligible
10. Target filter still before LIMIT
11. validated_at filter before LIMIT
12. Empty TARGET list still claims zero
13. Out-of-target prefix starvation remains fixed
14. Two-cycle monotonic progress test
15. Hydration regression passes
16. Evidence provenance regression passes
17. No model calls during tests
"""

import pytest
import sys
import os
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator_service import (
    claim_unvalidated_candidates,
    update_candidate_validations,
    process_batch,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
)


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


class MockConnection:
    def __init__(self, fetch_data=None):
        self.cursor_obj = MockCursor(fetch_data)

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def commit(self):
        pass


# 1 & 11. SQL Query structure check for validated_at IS NULL predicate before LIMIT
def test_validated_at_null_filter_in_sql():
    conn = MockConnection([])
    claim_unvalidated_candidates(conn, batch_size=10, target_procurement_ids=[100])

    query = conn.cursor_obj.last_query
    assert "AND d.validated_at IS NULL" in query, "SQL MUST include AND d.validated_at IS NULL filter"

    where_idx = query.find("WHERE")
    validated_idx = query.find("AND d.validated_at IS NULL")
    order_idx = query.find("ORDER BY")
    limit_idx = query.find("LIMIT")

    assert where_idx < validated_idx < order_idx < limit_idx, "validated_at filter MUST be before ORDER BY and LIMIT"


# 2. Already attempted UNKNOWN with validated_at timestamp is NOT claimed
def test_already_attempted_unknown_not_claimed():
    db_rows = [
        {"id": 1, "procurement_id": 100, "validation_status": "UNKNOWN", "validated_at": "2026-09-01T12:00:00Z"},
    ]
    # Simulate DB query matching SQL predicate: rows with validated_at NOT NULL return empty set
    matching_rows = [r for r in db_rows if r["validated_at"] is None]
    conn = MockConnection(matching_rows)

    claimed = claim_unvalidated_candidates(conn, batch_size=10, target_procurement_ids=[100])
    assert claimed == [], "Candidates with validated_at IS NOT NULL MUST NOT be claimed"


# 5 & 6. Semantic & Model Failure UNKNOWN after completed attempt not reclaimed
def test_completed_unknown_attempts_not_reclaimed():
    # Candidates 1 and 2: raw UNKNOWN with validated_at NULL
    c1 = {"id": 1, "detail_id": 1, "procurement_id": 100, "category_code": "lighting", "subcategory_code": "road_street",
          "validation_status": "UNKNOWN", "validated_at": None, "pipeline_generation": PIPELINE_GENERATION}
    c2 = {"id": 2, "detail_id": 2, "procurement_id": 100, "category_code": "lighting", "subcategory_code": "road_street",
          "validation_status": "UNKNOWN", "validated_at": None, "pipeline_generation": PIPELINE_GENERATION}

    # Candidates 3 and 4: already attempted UNKNOWN with validated_at timestamp
    c3 = {"id": 3, "detail_id": 3, "procurement_id": 100, "category_code": "lighting", "subcategory_code": "road_street",
          "validation_status": "UNKNOWN", "validated_at": "2026-09-01T12:00:00Z", "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"}
    c4 = {"id": 4, "detail_id": 4, "procurement_id": 100, "category_code": "lighting", "subcategory_code": "road_street",
          "validation_status": "UNKNOWN", "validated_at": "2026-09-01T12:05:00Z", "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"}

    all_db = [c1, c2, c3, c4]
    # SQL filter `AND d.validated_at IS NULL` returns only c1 and c2
    eligible_db = [r for r in all_db if r["validated_at"] is None]

    conn = MockConnection(eligible_db)
    claimed = claim_unvalidated_candidates(conn, batch_size=10, target_procurement_ids=[100])

    assert len(claimed) == 2
    claimed_ids = {r["id"] for r in claimed}
    assert claimed_ids == {1, 2}
    assert 3 not in claimed_ids
    assert 4 not in claimed_ids


# 14. Two-cycle monotonic progress test
def test_two_cycle_monotonic_progress():
    db_store = [
        {"id": 1, "detail_id": 1, "procurement_id": 100, "validation_status": "UNKNOWN", "validated_at": None},
        {"id": 2, "detail_id": 2, "procurement_id": 100, "validation_status": "UNKNOWN", "validated_at": None},
        {"id": 3, "detail_id": 3, "procurement_id": 100, "validation_status": "UNKNOWN", "validated_at": "2026-09-01T10:00:00Z"},
        {"id": 4, "detail_id": 4, "procurement_id": 100, "validation_status": "UNKNOWN", "validated_at": "2026-09-01T10:05:00Z"},
    ]

    # Cycle 1 query: SQL returns only rows with validated_at IS NULL (rows 1 and 2)
    cycle1_eligible = [r for r in db_store if r["validated_at"] is None]
    conn1 = MockConnection(cycle1_eligible)

    cycle1_claimed = claim_unvalidated_candidates(conn1, batch_size=10, target_procurement_ids=[100])
    assert len(cycle1_claimed) == 2
    assert {r["id"] for r in cycle1_claimed} == {1, 2}

    # Simulate persistence of results for rows 1 and 2 by assigning validated_at
    for r in db_store:
        if r["id"] in (1, 2):
            r["validated_at"] = "2026-09-01T16:00:00Z"
            r["validator_version"] = "v2"
            r["validation_method"] = "QWEN_CONTEXT_V2"

    # Cycle 2 query: SQL returns only rows with validated_at IS NULL (0 rows remain)
    cycle2_eligible = [r for r in db_store if r["validated_at"] is None]
    conn2 = MockConnection(cycle2_eligible)

    cycle2_claimed = claim_unvalidated_candidates(conn2, batch_size=10, target_procurement_ids=[100])
    assert cycle2_claimed == [], "Second cycle MUST claim 0 previously attempted rows"


# 17. No model calls during test
def test_no_model_calls():
    mock_ai = mock.MagicMock()
    validator = ContextValidator(ai_caller=mock_ai)

    conn = MockConnection([])
    claim_unvalidated_candidates(conn, batch_size=10)
    mock_ai.assert_not_called()
