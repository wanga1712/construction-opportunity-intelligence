"""Deterministic regression tests for Document Context Trust Boundary Repair (R3-4F-B-A).

Validates:
1. build_source_document_context() and build_visible_document_context() explicit authorities
2. Negative phrase list removed from model-visible prompt (NEGATIVE_PHRASE_VISIBLE_TO_MODEL=NO)
3. Supporting quote required for CONFIRMED and REJECTED (EMPTY_QUOTE_CAN_CONFIRM=NO, EMPTY_QUOTE_CAN_REJECT=NO)
4. Quote verification scope restricted STRICTLY to model-visible document context (QUOTE_VERIFICATION_SCOPE=EXACT_MODEL_VISIBLE_DOCUMENT_CONTEXT)
5. Quotes in truncated-out context (before/after/long matched line) demoted to UNKNOWN / HALLUCINATED_QUOTE (TRUNCATED_OUT_QUOTE_CAN_CONFIRM=NO, TRUNCATED_OUT_QUOTE_CAN_REJECT=NO)
6. Preserved quotes in visible matched line / retained before / retained after MUST pass verification
7. Quotes in metadata (category, subcategory, term, title, question, prompt) demoted to UNKNOWN / HALLUCINATED_QUOTE
8. Hard 3000 character limit enforcement (assert len(block) <= 3000)
9. Centered long matched line centered around matched_term (LONG_MATCH_POLICY=CENTERED_AROUND_MATCHED_TERM)
10. Strict V3 evidence provenance isolation in rebuild_affected_evidence()
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


# 2. Source vs Visible Document Context Authorities check
def test_source_vs_visible_document_context_authorities():
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
    source_ctx = build_source_document_context(candidate)
    visible_ctx = build_visible_document_context(candidate)

    assert "Строительные работы на объекте." in source_ctx
    assert "Нанесение битумной мастики в 2 слоя." in source_ctx
    assert "Приемка выполненных работ." in source_ctx

    assert "Нанесение битумной мастики в 2 слоя." in visible_ctx
    assert "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" in visible_ctx

    # Excludes metadata
    assert "Строительство детского сада" not in visible_ctx
    assert "Гидроизоляция" not in visible_ctx
    assert "Обмазочная гидроизоляция" not in visible_ctx
    assert "огнезащитная мастика" not in visible_ctx


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
    res_conf = validator._verify_and_gate_decision(raw_conf, candidate, build_visible_document_context(candidate))
    assert res_conf["decision"] == "UNKNOWN"
    assert res_conf["reason_code"] == "MISSING_SUPPORTING_QUOTE"
    assert res_conf["confidence"] == 0.0

    # Raw REJECTED with empty quote -> UNKNOWN / MISSING_SUPPORTING_QUOTE
    raw_rej = {"decision": "REJECTED", "confidence": 0.95, "supporting_quote": "", "reason": "Not target"}
    res_rej = validator._verify_and_gate_decision(raw_rej, candidate, build_visible_document_context(candidate))
    assert res_rej["decision"] == "UNKNOWN"
    assert res_rej["reason_code"] == "MISSING_SUPPORTING_QUOTE"
    assert res_rej["confidence"] == 0.0


# 6. Truncated-out quote MUST fail quote verification
def test_truncated_out_quote_demoted_to_unknown():
    validator = ContextValidator(max_context_chars=1200, ai_caller=lambda p: "")
    # Create long before text containing a secret string that gets truncated out
    long_before = ["SECRET_TRUNCATED_TEXT_ABC_HEADER_LINE"] + ["Преамбула документа " + ("X" * 100) for _ in range(20)]
    
    candidate = {
        "detail_id": 102,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник ДКУ 100 Вт.",
        "context_before": long_before,
        "context_after": ["Последующие работы."],
    }

    # Verify that SECRET_TRUNCATED_TEXT_ABC_HEADER_LINE is present in source context but TRUNCATED OUT of visible context
    source_ctx = build_source_document_context(candidate)
    visible_ctx = build_visible_document_context(candidate, max_context_chars=1200)

    assert "SECRET_TRUNCATED_TEXT_ABC_HEADER_LINE" in source_ctx
    assert "SECRET_TRUNCATED_TEXT_ABC_HEADER_LINE" not in visible_ctx

    # Attempting to confirm using truncated-out quote -> MUST BE DEMOTED TO UNKNOWN / HALLUCINATED_QUOTE
    raw_conf = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "SECRET_TRUNCATED_TEXT_ABC_HEADER_LINE", "reason": "OK"}
    res_conf = validator._verify_and_gate_decision(raw_conf, candidate, visible_ctx)
    assert res_conf["decision"] == "UNKNOWN"
    assert res_conf["reason_code"] == "HALLUCINATED_QUOTE"

    # Attempting to reject using truncated-out quote -> MUST BE DEMOTED TO UNKNOWN / HALLUCINATED_QUOTE
    raw_rej = {"decision": "REJECTED", "confidence": 0.95, "supporting_quote": "SECRET_TRUNCATED_TEXT_ABC_HEADER_LINE", "reason": "OK"}
    res_rej = validator._verify_and_gate_decision(raw_rej, candidate, visible_ctx)
    assert res_rej["decision"] == "UNKNOWN"
    assert res_rej["reason_code"] == "HALLUCINATED_QUOTE"


# 7. Preserved quote in visible matched line / retained before / retained after MUST pass verification
def test_visible_retained_quotes_pass_verification():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "detail_id": 103,
        "procurement_title": "Закупка оборудования уличного освещения",
        "category_name": "Освещение",
        "subcategory_name": "Освещение дорог и улиц",
        "matched_term": "светильник уличный",
        "context_before": ["Работы по объекту уличного освещения."],
        "matched_line": "Поставка оборудования светильник уличный согласно спецификации.",
        "context_after": ["Монтаж светильников в срок."],
    }
    vis_ctx = build_visible_document_context(candidate)

    # A. Quote in matched_line -> VALID
    raw_a = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Поставка оборудования светильник уличный", "reason": "OK"}
    assert validator._verify_and_gate_decision(raw_a, candidate, vis_ctx)["decision"] == "CONFIRMED"

    # B. Quote in context_before -> VALID
    raw_b = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Работы по объекту уличного освещения", "reason": "OK"}
    assert validator._verify_and_gate_decision(raw_b, candidate, vis_ctx)["decision"] == "CONFIRMED"

    # C. Quote in context_after -> VALID
    raw_c = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Монтаж светильников в срок", "reason": "OK"}
    assert validator._verify_and_gate_decision(raw_c, candidate, vis_ctx)["decision"] == "CONFIRMED"

    # D. Quote in category_name -> HALLUCINATED_QUOTE
    raw_d = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Освещение", "reason": "Metadata quote"}
    assert validator._verify_and_gate_decision(raw_d, candidate, vis_ctx)["decision"] == "UNKNOWN"

    # E. Quote in subcategory_name -> HALLUCINATED_QUOTE
    raw_e = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Освещение дорог и улиц", "reason": "Metadata quote"}
    assert validator._verify_and_gate_decision(raw_e, candidate, vis_ctx)["decision"] == "UNKNOWN"

    # F. Quote in procurement_title -> HALLUCINATED_QUOTE
    raw_f = {"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "Закупка оборудования уличного освещения", "reason": "Metadata quote"}
    assert validator._verify_and_gate_decision(raw_f, candidate, vis_ctx)["decision"] == "UNKNOWN"


# 8. Hard 3000 Character Contract & Centered Long Matched Line
def test_hard_3000_character_contract_and_long_matched_line():
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    long_before = ["Преамбула документа " + ("X" * 100) for _ in range(30)]
    long_after = ["Заключительные положения " + ("Y" * 100) for _ in range(30)]

    # Matched line with 2000 characters and matched_term in center
    prefix_line = "A" * 1000
    suffix_line = "B" * 1000
    pathological_matched_line = f"{prefix_line} СВЕТИЛЬНИК_ДКУ_УЛИЧНЫЙ {suffix_line}"

    candidate = {
        "procurement_id": 999,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник_дку_уличный",
        "matched_line": pathological_matched_line,
        "context_before": long_before,
        "context_after": long_after,
    }
    block = validator.build_context_block(candidate)

    # HARD CONTRACT: assert len(block) <= 3000
    assert len(block) <= 3000, f"Expected len(block) <= 3000, found {len(block)}"
    assert "СВЕТИЛЬНИК_ДКУ_УЛИЧНЫЙ" in block, "matched_term MUST be preserved when centered"
    assert "[ВОПРОС]" in block, "Question block MUST be preserved"
    assert "[ТЕНДЕР]" in block, "Metadata header MUST be preserved"
    assert "...[строка совпадения сокращена]..." in block


# 9. Strict V3 evidence provenance isolation
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
