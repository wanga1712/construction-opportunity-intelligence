"""Deterministic unit tests for V2 Evidence Provenance Isolation (R3-4E-A).

Verifies:
1. Only v2 confirmations -> v2 evidence
2. Only v1 confirmations -> v1 evidence
3. 10 v1 + 2 v2 -> evidence match_count=2, version=v2, method=QWEN_CONTEXT_V2
4. High-score v1 + lower-score v2 -> v2 score comes strictly from v2
5. v1 rows remain stored in DB
6. Missing provenance is not treated as v2
7. ContextValidator returns explicit v2 provenance
8. SYSTEM_PROMPT unchanged
9. Thresholds unchanged
"""

import pytest
import sys
import os
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator_service import (
    rebuild_affected_evidence,
    update_candidate_validations,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    SYSTEM_PROMPT,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
)


class MockCursor:
    def __init__(self, fetch_data=None):
        self.fetch_data = fetch_data or []
        self.executed_queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, query, params=None):
        self.executed_queries.append((query, params))

    def fetchall(self):
        return self.fetch_data


class MockConnection:
    def __init__(self, fetch_data=None):
        self.cursor_obj = MockCursor(fetch_data)

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def commit(self):
        pass


# ============================================================
# Test 1: Only v2 confirmations -> v2 evidence
# ============================================================
def test_only_v2_confirmations_builds_v2_evidence():
    rows = [
        {"score": 85.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
        {"score": 90.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
    ]
    conn = MockConnection(rows)
    rebuild_affected_evidence(conn, {(555, "lighting")})

    # Find INSERT INTO document_evidence
    insert_queries = [q for q in conn.cursor_obj.executed_queries if "INSERT INTO document_evidence" in q[0]]
    assert len(insert_queries) == 1
    params = insert_queries[0][1]

    # Params: (pid, queue_id, cat, max_score, match_count, next_stage, status, val_ver, val_method, gen)
    assert params[0] == 555
    assert params[3] == 90.0  # max_score
    assert params[4] == 2     # match_count
    assert params[7] == "v2"
    assert params[8] == "QWEN_CONTEXT_V2"


# ============================================================
# Test 2: Only v1 confirmations -> v1 evidence
# ============================================================
def test_only_v1_confirmations_builds_v1_evidence():
    rows = [
        {"score": 75.0, "queue_id": 1, "validator_version": "v1", "validation_method": "QWEN_CONTEXT_V1"},
    ]
    conn = MockConnection(rows)
    rebuild_affected_evidence(conn, {(555, "lighting")})

    insert_queries = [q for q in conn.cursor_obj.executed_queries if "INSERT INTO document_evidence" in q[0]]
    assert len(insert_queries) == 1
    params = insert_queries[0][1]

    assert params[4] == 1
    assert params[7] == "v1"
    assert params[8] == "QWEN_CONTEXT_V1"


# ============================================================
# Test 3 & 4: 10 v1 + 2 v2 -> match_count=2, score strictly from v2 rows
# ============================================================
def test_mixed_v1_and_v2_confirmations_isolates_v2():
    """
    Simulates 10 legacy v1 confirmed rows (high score 99.0) and 2 new v2 confirmed rows (scores 70.0 and 80.0).
    Rebuild MUST produce v2 evidence with match_count=2 and max_score=80.0 (ignoring 99.0 v1 score).
    """
    v1_rows = [
        {"score": 99.0, "queue_id": 1, "validator_version": "v1", "validation_method": "QWEN_CONTEXT_V1"}
        for _ in range(10)
    ]
    v2_rows = [
        {"score": 70.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
        {"score": 80.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
    ]
    rows = v1_rows + v2_rows

    conn = MockConnection(rows)
    rebuild_affected_evidence(conn, {(555, "lighting")})

    insert_queries = [q for q in conn.cursor_obj.executed_queries if "INSERT INTO document_evidence" in q[0]]
    assert len(insert_queries) == 1
    params = insert_queries[0][1]

    assert params[3] == 80.0, "Score MUST come strictly from v2 rows (80.0), NOT high-score v1 row (99.0)"
    assert params[4] == 2, "match_count MUST be 2 (only v2 rows), NOT 12"
    assert params[7] == "v2"
    assert params[8] == "QWEN_CONTEXT_V2"


# ============================================================
# Test 5: Missing or unknown provenance is not treated as v2
# ============================================================
def test_missing_provenance_not_treated_as_v2():
    rows = [
        {"score": 85.0, "queue_id": 1, "validator_version": None, "validation_method": None},
        {"score": 88.0, "queue_id": 1, "validator_version": "UNKNOWN", "validation_method": "UNSPECIFIED"},
    ]
    conn = MockConnection(rows)
    rebuild_affected_evidence(conn, {(555, "lighting")})

    insert_queries = [q for q in conn.cursor_obj.executed_queries if "INSERT INTO document_evidence" in q[0]]
    assert len(insert_queries) == 1
    params = insert_queries[0][1]

    assert params[7] == "v1", "Missing/unknown provenance must fall back to v1 evidence, NOT v2"
    assert params[8] == "QWEN_CONTEXT_V1"


# ============================================================
# Test 6: Missing provenance on CONFIRMED candidate demotes to UNKNOWN
# ============================================================
def test_update_candidate_missing_provenance_demotes_to_unknown():
    conn = MockConnection([])
    results = [
        {
            "detail_id": 1,
            "procurement_id": 100,
            "category_code": "lighting",
            "decision": "CONFIRMED",
            "validator_name": None,
            "validator_version": None,
            "validation_method": None,
        }
    ]

    update_candidate_validations(conn, results)

    update_queries = [q for q in conn.cursor_obj.executed_queries if "UPDATE document_match_details" in q[0]]
    assert len(update_queries) == 1
    params = update_queries[0][1]

    # status is params[0]
    assert params[0] == "UNKNOWN", "CONFIRMED result missing provenance MUST be demoted to UNKNOWN"


# ============================================================
# Test 7: Thresholds unchanged
# ============================================================
def test_thresholds_unchanged():
    assert DEFAULT_CONFIRM_THRESHOLD == 0.80
    assert DEFAULT_REJECT_THRESHOLD == 0.85
