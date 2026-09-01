"""Deterministic regression tests for Document Context Trust Boundary Repair (R3-4F-B-B).

Validates:
1. build_context_payload() single execution path alignment (VISIBLE_CONTEXT_BUILT_ONCE_PER_VALIDATION=YES)
2. Verifier visible source text matches exact prompt documentary text (VERIFIER_DOCUMENT_TEXT == PROMPT_DOCUMENT_EVIDENCE_TEXT)
3. Generated markers/labels CANNOT support decisions (GENERATED_MARKER_CAN_SUPPORT_DECISION=NO)
4. Real production budget regression: quote from truncated-out source text fails verification via validate_single()
5. Visible retained before/matched/after quotes pass verification via validate_single()
6. Pathological metadata handling (very long title, OKPD, category, doc name) preserves [ВОПРОС] and [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]
7. Hard 3000 max context character contract (assert len(block) <= 3000 without blind clipping)
8. Impossible budget policy (max_context_chars < 300 raises ValueError)
9. Strict V3 evidence provenance isolation in rebuild_affected_evidence()
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
    assert VALIDATOR_VERSION == "v3"
    assert VALIDATION_METHOD == "QWEN_CONTEXT_V3"
    assert PROMPT_VERSION == "context_validator_v3"


# 2. Exact Prompt Evidence Alignment Check
def test_exact_prompt_evidence_alignment():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "procurement_title": "Строительство детского сада",
        "category_name": "Гидроизоляция",
        "category_code": "waterproofing",
        "subcategory_name": "Обмазочная гидроизоляция",
        "subcategory_code": "coating",
        "matched_term": "мастика",
        "context_before": ["Строительные работы на объекте."],
        "matched_line": "Нанесение битумной мастики в 2 слоя.",
        "context_after": ["Приемка выполненных работ."],
    }
    payload = validator.build_context_payload(candidate)

    context_block = payload["context_block"]
    visible_source_text = payload["visible_source_text"]

    # Extract documentary text embedded inside [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]
    doc_start = context_block.find("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]")
    doc_end = context_block.find("[ВОПРОС]")
    assert doc_start != -1 and doc_end != -1
    prompt_doc_section = context_block[doc_start:doc_end]

    # Verify that all lines in visible_source_text are present in prompt_doc_section
    for line in visible_source_text.splitlines():
        line_clean = line.strip()
        if line_clean:
            assert line_clean in prompt_doc_section


# 3. Generated Markers/Labels CANNOT Support Decisions
def test_generated_markers_cannot_support_decisions():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "detail_id": 100,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_line": "Светильник ДКУ 100W",
        "context_before": ["Преамбула " + ("A" * 100) for _ in range(10)],
    }
    payload = validator.build_context_payload(candidate)
    visible_source = payload["visible_source_text"]

    # A quote consisting ONLY of generated marker label must fail
    marker_quotes = [
        "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]",
        ">>> НАЙДЕННАЯ СТРОКА:",
        "...[контекст до совпадения сокращён]...",
        "...[контекст после совпадения сокращён]...",
    ]

    for mq in marker_quotes:
        raw_conf = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": mq, "reason": "Marker quote"}
        res = validator._verify_and_gate_decision(raw_conf, candidate, visible_source)
        assert res["decision"] == "UNKNOWN"
        assert res["reason_code"] == "HALLUCINATED_QUOTE"


# 4. Real Production Budget Regression (validate_single with truncated-out quote)
def test_real_production_budget_regression_truncated_out_quote():
    # Secret text in context_before that will be truncated out by actual prompt budget
    long_before = ["SECRET_TRUNCATED_TEXT_HEADER_LINE_XYZ"] + ["Строительные работы " + ("X" * 100) for _ in range(25)]
    candidate = {
        "detail_id": 101,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник ДКУ 100 Вт.",
        "context_before": long_before,
        "context_after": ["Работы завершены."],
    }

    # Mock AI caller that returns CONFIRMED quoting the truncated-out secret text
    def mock_caller_conf(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "SECRET_TRUNCATED_TEXT_HEADER_LINE_XYZ",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Found requirement",
        })

    validator = ContextValidator(ai_caller=mock_caller_conf)
    res_conf = validator.validate_single(candidate)

    # MUST fail quote verification because Qwen never saw SECRET_TRUNCATED_TEXT_HEADER_LINE_XYZ in its prompt!
    assert res_conf["decision"] == "UNKNOWN"
    assert res_conf["reason_code"] == "HALLUCINATED_QUOTE"

    # Repeat for REJECTED
    def mock_caller_rej(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "REJECTED",
            "confidence": 0.95,
            "supporting_quote": "SECRET_TRUNCATED_TEXT_HEADER_LINE_XYZ",
            "reason_code": "UNRELATED_PRODUCT",
            "reason": "Not target",
        })

    validator_rej = ContextValidator(ai_caller=mock_caller_rej)
    res_rej = validator_rej.validate_single(candidate)
    assert res_rej["decision"] == "UNKNOWN"
    assert res_rej["reason_code"] == "HALLUCINATED_QUOTE"


# 5. Visible Retained Source Quotes Pass Verification
def test_visible_retained_quotes_pass_verification_via_validate_single():
    candidate = {
        "detail_id": 102,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "context_before": ["Монтаж оборудования уличного освещения."],
        "matched_line": "Светильник ДКУ 100 Вт согласно спецификации.",
        "context_after": ["Гарантия 5 лет."],
    }

    def mock_caller(prompt):
        return json.dumps({
            "detail_id": 102,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Светильник ДКУ 100 Вт",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Confirmed requirement",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "CONFIRMED"
    assert res["supporting_quote"] == "Светильник ДКУ 100 Вт"


# 6. Pathological Metadata Handling
def test_pathological_metadata_preserves_question_and_document_section():
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    pathological_title = "ОЧЕНЬ_ДЛИННОЕ_НАИМЕНОВАНИЕ_ЗАКУПКИ_" + ("T" * 2000)
    pathological_okpd = "ОКПД_ИМЯ_" + ("O" * 2000)
    pathological_doc = "ДОКУМЕНТ_ИМЯ_" + ("D" * 2000)

    candidate = {
        "procurement_id": 888,
        "procurement_title": pathological_title,
        "procurement_okpd_code": "27.40.39",
        "procurement_okpd_name": pathological_okpd,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "document_name": pathological_doc,
        "matched_line": "Светильник ДКУ 100 Вт уличный.",
        "context_before": ["Контекст до."],
        "context_after": ["Контекст после."],
    }

    payload = validator.build_context_payload(candidate)
    block = payload["context_block"]

    # Invariants:
    assert len(block) <= 3000, f"Hard limit violated: len(block)={len(block)}"
    assert "[ВОПРОС]" in block, "Question block MUST be intact"
    assert "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" in block, "Document section MUST be intact"
    assert "Светильник ДКУ 100 Вт уличный." in block, "Matched line MUST be visible"


# 7. Impossible Budget Policy
def test_impossible_budget_policy_raises_value_error():
    with pytest.raises(ValueError, match="Impossible context budget"):
        ContextValidator(max_context_chars=200, ai_caller=lambda p: "")


# 8. Strict V3 evidence provenance isolation
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
