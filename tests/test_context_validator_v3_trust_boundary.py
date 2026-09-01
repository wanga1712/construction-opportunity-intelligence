"""Deterministic regression tests for Document Context Trust Boundary Repair (R3-4F-B-C).

Validates:
1. Pure source text contains ONLY original factual document characters (ZERO generated markers)
2. Retained match source is a pure substring of the original matched_line (VISIBLE_MATCH_SOURCE_IS_SUBSTRING_OF_ORIGINAL=YES)
3. Truncation markers (e.g. "строка совпадения сокращена") CANNOT support decisions (MATCH_TRUNCATION_MARKER_CAN_CONFIRM=NO, MATCH_TRUNCATION_MARKER_CAN_REJECT=NO)
4. Quotes from actual retained source substrings pass verification
5. Pathological metadata test matrix (title, OKPD, category, subcategory, term, doc_name = 10,000 chars each) preserves [ВОПРОС] and [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]
6. Hard 3000 max context character contract (assert len(block) <= 3000)
7. True impossible budget check (ValueError when max_context_chars is smaller than required minimum overhead)
8. Strict V3 evidence provenance isolation in rebuild_affected_evidence()
"""

import pytest
import sys
import os
import json
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    build_source_document_context,
    build_visible_document_context,
    build_document_context,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
)
from tender_documents_research.document_processor.context_validator_service import (
    rebuild_affected_evidence,
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


# 1. Versioning check
def test_v3_versioning_constants():
    assert VALIDATOR_VERSION in ("v3", "v4")
    assert VALIDATION_METHOD in ("QWEN_CONTEXT_V3", "QWEN_CONTEXT_V4")
    assert PROMPT_VERSION in ("context_validator_v3", "context_validator_v4")


# 2. Pure Source Text Contains Zero Generated Markers
def test_pure_source_text_contains_zero_generated_markers():
    validator = ContextValidator(ai_caller=lambda p: "")
    pathological_mline = ("X" * 1000) + " СВЕТИЛЬНИК_ДКУ " + ("Y" * 1000)
    candidate = {
        "procurement_id": 100,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник_дку",
        "matched_line": pathological_mline,
        "context_before": ["Перед " + ("A" * 100) for _ in range(20)],
        "context_after": ["После " + ("B" * 100) for _ in range(20)],
    }
    payload = validator.build_context_payload(candidate)
    visible_source = payload["visible_source_text"]

    generated_markers = [
        "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]",
        ">>> НАЙДЕННАЯ СТРОКА:",
        "...[контекст до совпадения сокращён]...",
        "...[контекст после совпадения сокращён]...",
        "...[строка совпадения сокращена]...",
    ]
    for gm in generated_markers:
        assert gm not in visible_source, f"Generated marker '{gm}' MUST NOT be in visible_source_text"

    assert "СВЕТИЛЬНИК_ДКУ" in visible_source


# 3. Quote Test for Match Truncation Marker
def test_match_truncation_marker_cannot_support_decision():
    pathological_mline = ("PRE_" * 500) + " СВЕТИЛЬНИК_УЛИЧНЫЙ_ДКУ " + ("POST_" * 500)
    candidate = {
        "detail_id": 101,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник_уличный_дку",
        "matched_line": pathological_mline,
    }

    # A. Quote consisting of truncation marker text -> UNKNOWN / HALLUCINATED_QUOTE
    def mock_caller_marker_conf(p):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "строка совпадения сокращена",
            "reason": "Quoting display marker",
        })

    validator = ContextValidator(ai_caller=mock_caller_marker_conf)
    res_conf = validator.validate_single(candidate)
    assert res_conf["decision"] == "UNKNOWN"
    assert res_conf["reason_code"] == "HALLUCINATED_QUOTE"

    def mock_caller_marker_rej(p):
        return json.dumps({
            "detail_id": 101,
            "decision": "REJECTED",
            "confidence": 0.95,
            "supporting_quote": "строка совпадения сокращена",
            "reason": "Quoting display marker",
        })

    validator_rej = ContextValidator(ai_caller=mock_caller_marker_rej)
    res_rej = validator_rej.validate_single(candidate)
    assert res_rej["decision"] == "UNKNOWN"
    assert res_rej["reason_code"] == "HALLUCINATED_QUOTE"

    # B. Quote from actual retained source substring -> PASSES (CONFIRMED)
    def mock_caller_valid(p):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "СВЕТИЛЬНИК_УЛИЧНЫЙ_ДКУ",
            "reason": "Quoting actual retained source",
        })

    validator_valid = ContextValidator(ai_caller=mock_caller_valid)
    res_valid = validator_valid.validate_single(candidate)
    assert res_valid["decision"] == "CONFIRMED"
    assert res_valid["supporting_quote"] == "СВЕТИЛЬНИК_УЛИЧНЫЙ_ДКУ"


# 4. Pathological Metadata Test Matrix (10,000 chars for each field)
@pytest.mark.parametrize("field_name", [
    "procurement_title",
    "procurement_okpd_name",
    "category_name",
    "subcategory_name",
    "matched_term",
    "document_name",
    "ALL_SIMULTANEOUS",
])
def test_pathological_metadata_matrix(field_name):
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    huge_str = "PATHOLOGICAL_10K_" + ("Z" * 10000)

    candidate = {
        "procurement_id": 888,
        "procurement_title": huge_str if field_name in ("procurement_title", "ALL_SIMULTANEOUS") else "Нормальный заголовок",
        "procurement_okpd_code": "27.40.39",
        "procurement_okpd_name": huge_str if field_name in ("procurement_okpd_name", "ALL_SIMULTANEOUS") else "Светильники",
        "category_code": "lighting",
        "category_name": huge_str if field_name in ("category_name", "ALL_SIMULTANEOUS") else "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": huge_str if field_name in ("subcategory_name", "ALL_SIMULTANEOUS") else "Уличное освещение",
        "matched_term": huge_str if field_name in ("matched_term", "ALL_SIMULTANEOUS") else "светильник",
        "document_name": huge_str if field_name in ("document_name", "ALL_SIMULTANEOUS") else "Спецификация.pdf",
        "matched_line": "Светильник ДКУ 100 Вт уличный.",
        "context_before": ["Контекст до."],
        "context_after": ["Контекст после."],
    }

    payload = validator.build_context_payload(candidate)
    block = payload["context_block"]
    vis_source = payload["visible_source_text"]

    # HARD CONTRACT assertions:
    assert len(block) <= 3000, f"Field '{field_name}': len(block)={len(block)} exceeds max_context_chars=3000"
    assert "[ВОПРОС]" in block, f"Field '{field_name}': [ВОПРОС] block MUST be intact"
    assert "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" in block, f"Field '{field_name}': [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ] MUST be intact"
    assert "Светильник ДКУ 100 Вт уличный." in block, f"Field '{field_name}': Matched line MUST be visible"

    # Pure source check: ZERO generated markers in vis_source
    assert "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" not in vis_source
    assert ">>> НАЙДЕННАЯ СТРОКА:" not in vis_source


# 5. True Impossible Budget Check (raises ValueError during context payload build)
def test_true_impossible_budget_check_raises_value_error():
    candidate = {
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_line": "Светильник ДКУ",
    }
    validator = ContextValidator(max_context_chars=500, ai_caller=lambda p: "")
    with pytest.raises(ValueError, match="Impossible context budget"):
        validator.build_context_payload(candidate)


# 6. Strict V3 evidence provenance isolation
def test_strict_v3_evidence_provenance():
    mock_conn = MockConnection()

    mock_conn.cursor_obj.fetch_data = [
        {"score": 90.0, "queue_id": 1, "validator_version": "v3", "validation_method": "QWEN_CONTEXT_V3"},
        {"score": 85.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
    ]
    rebuild_affected_evidence(mock_conn, {(100, "lighting")})
    query_a = mock_conn.cursor_obj.last_query
    assert "INSERT INTO document_evidence" in query_a
    params_a = mock_conn.cursor_obj.last_params
    assert params_a[7] == "v3"  # validator_version
    assert params_a[8] == "QWEN_CONTEXT_V3"  # validation_method


# 7. Zero-Slice Bug Regression Tests (Cases A, B, C, D, E)
def test_zero_slice_before_text_not_restored_by_negative_zero_index():
    """Case A: avail_before_net = 0 MUST yield used_before == "", NOT entire before_text."""
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    huge_before = ["СТРОКА_ДО_" + str(i) + " " + ("B" * 500) for i in range(100)] # ~50,000 chars
    candidate = {
        "detail_id": 901,
        "procurement_id": 901,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт." + ("M" * 1600),
        "context_before": huge_before,
        "context_after": [],
    }
    payload = validator.build_context_payload(candidate)
    vis_source = payload["visible_source_text"]
    block = payload["context_block"]

    # Case C: Context block length contract <= 3000
    assert len(block) <= 3000, f"context_block len={len(block)} exceeds max_context_chars=3000"

    # Case A & D: Entire huge before_text MUST NOT be in visible_source_text
    assert "СТРОКА_ДО_99" not in vis_source, "Truncated-out before_text MUST NOT be in visible_source_text"
    assert "СТРОКА_ДО_0" not in vis_source, "Truncated-out before_text MUST NOT be restored by [-0:] slice"


def test_zero_slice_after_text_not_restored_by_negative_zero_index():
    """Case B: avail_after_net = 0 MUST yield used_after == "", NOT entire after_text."""
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    huge_after = ["СТРОКА_ПОСЛЕ_" + str(i) + " " + ("A" * 500) for i in range(100)] # ~50,000 chars
    candidate = {
        "detail_id": 902,
        "procurement_id": 902,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт." + ("M" * 1600),
        "context_before": [],
        "context_after": huge_after,
    }
    payload = validator.build_context_payload(candidate)
    vis_source = payload["visible_source_text"]
    block = payload["context_block"]

    # Case C: Context block length contract <= 3000
    assert len(block) <= 3000, f"context_block len={len(block)} exceeds max_context_chars=3000"

    # Case B & D: Entire huge after_text MUST NOT be in visible_source_text
    assert "СТРОКА_ПОСЛЕ_99" not in vis_source, "Truncated-out after_text MUST NOT be in visible_source_text"


def test_quote_from_zero_slice_excluded_source_demoted_to_unknown():
    """Case E: Quote from excluded source text -> UNKNOWN / HALLUCINATED_QUOTE."""
    huge_before = ["СЕКРЕТНЫЙ_ДОКУМЕНТ_ДО_" + str(i) + " " + ("B" * 500) for i in range(100)]
    candidate = {
        "detail_id": 903,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт." + ("M" * 1600),
        "context_before": huge_before,
        "context_after": [],
    }

    # Model attempts to quote text from excluded/truncated before_text
    def mock_caller_excluded_quote(p):
        return json.dumps({
            "detail_id": 903,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "СЕКРЕТНЫЙ_ДОКУМЕНТ_ДО_50",
            "reason": "Quoting excluded text",
        })

    validator = ContextValidator(ai_caller=mock_caller_excluded_quote)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "HALLUCINATED_QUOTE"
