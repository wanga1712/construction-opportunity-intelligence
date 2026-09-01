"""Deterministic regression tests for Document Context Trust Boundary Repair (R3-4F-B).

Validates:
1. Negative phrase list removed from model-visible prompt (NEGATIVE_PHRASE_VISIBLE_TO_MODEL=NO)
2. Supporting quote required for CONFIRMED and REJECTED (EMPTY_QUOTE_CAN_CONFIRM=NO, EMPTY_QUOTE_CAN_REJECT=NO)
3. Quote verification scope restricted ONLY to document context (QUOTE_VERIFICATION_SCOPE=DOCUMENT_CONTEXT_ONLY)
4. Quotes in metadata (category, subcategory, term, title, question, prompt) demoted to UNKNOWN / HALLUCINATED_QUOTE
5. Centered context budgeting preserves matched_line, metadata, and question (MATCHED_LINE_PRESERVED=YES, QUESTION_PRESERVED=YES)
6. Strict V3 evidence provenance isolation in rebuild_affected_evidence()
"""

import pytest
import sys
import os
import json
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
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


# 2. Document Context Authority check
def test_build_document_context_authority():
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
        "negative_phrases": ["огнезащитная мастика"],
    }
    doc_ctx = build_document_context(candidate)

    assert "Строительные работы на объекте." in doc_ctx
    assert "Нанесение битумной мастики в 2 слоя." in doc_ctx
    assert "Приемка выполненных работ." in doc_ctx

    # Excludes metadata
    assert "Строительство детского сада" not in doc_ctx
    assert "Гидроизоляция" not in doc_ctx
    assert "Обмазочная гидроизоляция" not in doc_ctx
    assert "огнезащитная мастика" not in doc_ctx
    assert "[ТЕНДЕР]" not in doc_ctx
    assert "[ВОПРОС]" not in doc_ctx


# 3. Model-visible prompt does NOT contain negative phrase list
def test_negative_phrases_removed_from_model_prompt():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "procurement_id": 100,
        "category_code": "waterproofing",
        "subcategory_code": "coating",
        "matched_term": "мастика",
        "negative_phrases": ["ОГНЕЗАЩИТНЫЙ_СОСТАВ_АБСОЛЮТНО_НЕЦЕЛЕВОЙ"],
        "context_before": ["Перед нанесением."],
        "matched_line": "Битумная мастика 10 кг.",
        "context_after": ["После нанесения."],
    }
    block = validator.build_context_block(candidate)

    assert "ОГНЕЗАЩИТНЫЙ_СОСТАВ_АБСОЛЮТНО_НЕЦЕЛЕВОЙ" not in block
    assert "[СТОП-ФРАЗЫ КАТЕГОРИИ]" not in block


# 4 & 5. Empty quote enforcement
def test_empty_quote_demotes_confirmed_and_rejected_to_unknown():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "detail_id": 101,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_line": "Светильник ДКУ 100W",
    }

    # Raw CONFIRMED with empty quote -> UNKNOWN / MISSING_SUPPORTING_QUOTE
    raw_conf = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "", "reason": "Looks good"}
    res_conf = validator._verify_and_gate_decision(raw_conf, candidate, build_document_context(candidate))
    assert res_conf["decision"] == "UNKNOWN"
    assert res_conf["reason_code"] == "MISSING_SUPPORTING_QUOTE"
    assert res_conf["confidence"] == 0.0

    # Raw REJECTED with empty quote -> UNKNOWN / MISSING_SUPPORTING_QUOTE
    raw_rej = {"decision": "REJECTED", "confidence": 0.95, "supporting_quote": "", "reason": "Not target"}
    res_rej = validator._verify_and_gate_decision(raw_rej, candidate, build_document_context(candidate))
    assert res_rej["decision"] == "UNKNOWN"
    assert res_rej["reason_code"] == "MISSING_SUPPORTING_QUOTE"
    assert res_rej["confidence"] == 0.0


# 6. Quote verification scope restricted ONLY to document context
def test_quote_in_metadata_demoted_to_unknown():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "detail_id": 102,
        "procurement_title": "Закупка оборудования уличного освещения",
        "category_name": "Освещение",
        "subcategory_name": "Освещение дорог и улиц",
        "matched_term": "светильник уличный",
        "context_before": ["Работы по объекту."],
        "matched_line": "Поставка оборудования согласно спецификации.",
        "context_after": ["Монтаж в срок."],
    }
    doc_ctx = build_document_context(candidate)

    # A. Quote in matched_line -> VALID
    raw_a = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Поставка оборудования", "reason": "OK"}
    assert validator._verify_and_gate_decision(raw_a, candidate, doc_ctx)["decision"] == "CONFIRMED"

    # B. Quote in context_before -> VALID
    raw_b = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Работы по объекту", "reason": "OK"}
    assert validator._verify_and_gate_decision(raw_b, candidate, doc_ctx)["decision"] == "CONFIRMED"

    # C. Quote in context_after -> VALID
    raw_c = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Монтаж в срок", "reason": "OK"}
    assert validator._verify_and_gate_decision(raw_c, candidate, doc_ctx)["decision"] == "CONFIRMED"

    # D. Quote in category_name -> HALLUCINATED_QUOTE
    raw_d = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Освещение", "reason": "Metadata quote"}
    assert validator._verify_and_gate_decision(raw_d, candidate, doc_ctx)["decision"] == "UNKNOWN"

    # E. Quote in subcategory_name -> HALLUCINATED_QUOTE
    raw_e = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Освещение дорог и улиц", "reason": "Metadata quote"}
    assert validator._verify_and_gate_decision(raw_e, candidate, doc_ctx)["decision"] == "UNKNOWN"

    # F. Quote in procurement_title -> HALLUCINATED_QUOTE
    raw_f = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Закупка оборудования уличного освещения", "reason": "Metadata quote"}
    assert validator._verify_and_gate_decision(raw_f, candidate, doc_ctx)["decision"] == "UNKNOWN"


# 7. Centered context budgeting preserves matched_line, metadata, and question
def test_centered_context_budgeting_preserves_matched_line_and_question():
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    long_before = ["Преамбула документа " + ("X" * 100) for _ in range(30)]
    long_after = ["Заключительные положения " + ("Y" * 100) for _ in range(30)]

    candidate = {
        "procurement_id": 999,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "КРИТИЧЕСКАЯ_СТРОКА_СОВПАДЕНИЯ: Светильник ДКУ 100 Вт.",
        "context_before": long_before,
        "context_after": long_after,
    }
    block = validator.build_context_block(candidate)

    assert len(block) <= 3200  # Budget allocation respects max_context_chars
    assert "КРИТИЧЕСКАЯ_СТРОКА_СОВПАДЕНИЯ: Светильник ДКУ 100 Вт." in block, "matched_line MUST be preserved"
    assert "[ВОПРОС]" in block, "Question block MUST be preserved"
    assert "[ТЕНДЕР]" in block, "Metadata header MUST be preserved"
    assert "...[контекст до совпадения сокращён]..." in block
    assert "...[контекст после совпадения сокращён]..." in block


# 8. Strict V3 evidence provenance isolation
def test_strict_v3_evidence_provenance():
    mock_conn = MockConnection()

    # Case A: v3 trusted CONFIRMED rows exist -> aggregates ONLY v3
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
