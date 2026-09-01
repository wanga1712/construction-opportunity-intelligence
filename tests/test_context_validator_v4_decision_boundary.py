# -*- coding: utf-8 -*-
"""Deterministic unit tests for ContextValidator V4 Decision Boundary Prompt Repair (R3-4F-E-A).

Validates:
1. V4 versioning constants (VALIDATOR_VERSION="v4", VALIDATION_METHOD="QWEN_CONTEXT_V4", PROMPT_VERSION="context_validator_v4")
2. Prompt contract rules (truncation markers, taxonomy-agnostic literal subcategory rule, brand/model not required, address/org/person/legal -> REJECTED)
3. SYSTEM_PROMPT and question_block consistency tests
4. Mocked decision contract tests (CONFIRMED, REJECTED for person/admin, UNKNOWN for genuine ambiguity, quote gating, demotions)
5. Strict V4 evidence provenance isolation in rebuild_affected_evidence()
"""

import pytest
import sys
import os
import json
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    validate_candidates,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
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
def test_v4_versioning_constants():
    assert VALIDATOR_NAME == "context_validator"
    assert VALIDATOR_VERSION == "v4"
    assert VALIDATION_METHOD == "QWEN_CONTEXT_V4"
    assert PROMPT_VERSION == "context_validator_v4"


# 2. Prompt Contract Tests
def test_prompt_contract_truncation_markers_not_automatic_unknown():
    assert "указывают лишь на то, что часть окружающего текста была опущена" in SYSTEM_PROMPT
    assert "Сокращение окружающего контекста само по себе НЕ ЯВЛЯЕТСЯ причиной для UNKNOWN" in SYSTEM_PROMPT
    assert "НЕ означают неполноту" not in SYSTEM_PROMPT


def test_prompt_contract_literal_subcategory_not_required_taxonomy_agnostic():
    assert "Документ НЕ ОБЯЗАН содержать дословное название категории или подкатегории" in SYSTEM_PROMPT
    assert "уличное освещение" not in SYSTEM_PROMPT
    assert "Светильник светодиодный" not in SYSTEM_PROMPT


def test_prompt_contract_brand_model_not_required():
    assert "Указание бренда, производителя, модели, артикула или ГОСТа НЕ ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ" in SYSTEM_PROMPT


def test_prompt_contract_address_org_person_legal_rejected():
    assert "ADDRESS_OR_LOCATION_ONLY" in SYSTEM_PROMPT
    assert "ORGANIZATION_NAME_ONLY" in SYSTEM_PROMPT
    assert "LEGAL_ADMINISTRATIVE_TEXT" in SYSTEM_PROMPT
    assert "ФИО или должностью" in SYSTEM_PROMPT


def test_prompt_question_block_consistency():
    validator = ContextValidator(ai_caller=lambda p: "")
    candidate = {
        "category_code": "lighting",
        "category_name": "Освещение",
        "subcategory_code": "road_street",
        "subcategory_name": "Уличное освещение",
        "matched_term": "светильник",
        "matched_line": "Светильник светодиодный 100 Вт.",
    }
    payload = validator.build_context_payload(candidate)
    block = payload["context_block"]

    assert "[ВОПРОС]" in block
    assert "[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]" in block
    assert "игнорируй текст маркеров и оценивай сохранившийся документальный источник" in block
    assert "Наличие дословной фразы подкатегории или бренда НЕ требуется" in block
    assert "адресу, названию организации, ФИО/должности, юридическим реквизитам" in block
    assert "НЕ означают неполноту" not in block


# 3. System / Question Consistency Deterministic Tests (Section 7)
def test_system_question_consistency_truncation_no_automatic_unknown():
    validator = ContextValidator(ai_caller=lambda p: "")
    payload = validator.build_context_payload({
        "category_code": "c", "category_name": "cn",
        "subcategory_code": "sc", "subcategory_name": "scn",
        "matched_term": "t", "matched_line": "line"
    })
    block = payload["context_block"]

    assert "НЕ ЯВЛЯЕТСЯ причиной для UNKNOWN" in SYSTEM_PROMPT
    assert "НЕ означают неполноту" not in SYSTEM_PROMPT
    assert "НЕ означают неполноту" not in block


def test_system_question_consistency_literal_subcategory():
    validator = ContextValidator(ai_caller=lambda p: "")
    payload = validator.build_context_payload({
        "category_code": "c", "category_name": "cn",
        "subcategory_code": "sc", "subcategory_name": "scn",
        "matched_term": "t", "matched_line": "line"
    })
    block = payload["context_block"]

    assert "Документ НЕ ОБЯЗАН содержать дословное название категории или подкатегории" in SYSTEM_PROMPT
    assert "Наличие дословной фразы подкатегории или бренда НЕ требуется" in block


def test_system_question_consistency_negative_boundary():
    validator = ContextValidator(ai_caller=lambda p: "")
    payload = validator.build_context_payload({
        "category_code": "c", "category_name": "cn",
        "subcategory_code": "sc", "subcategory_name": "scn",
        "matched_term": "t", "matched_line": "line"
    })
    block = payload["context_block"]

    for term in ["адресу", "организации", "юридическим реквизитам"]:
        assert term in block
    assert "ADDRESS_OR_LOCATION_ONLY" in SYSTEM_PROMPT
    assert "ORGANIZATION_NAME_ONLY" in SYSTEM_PROMPT
    assert "LEGAL_ADMINISTRATIVE_TEXT" in SYSTEM_PROMPT


def test_system_question_consistency_unknown_not_default():
    validator = ContextValidator(ai_caller=lambda p: "")
    payload = validator.build_context_payload({
        "category_code": "c", "category_name": "cn",
        "subcategory_code": "sc", "subcategory_name": "scn",
        "matched_term": "t", "matched_line": "line"
    })
    block = payload["context_block"]

    assert 'UNKNOWN НЕ ЯВЛЯЕТСЯ "ответом по умолчанию"' in SYSTEM_PROMPT
    assert "'UNKNOWN' выбирай ТОЛЬКО при реальной фактологической неоднозначности" in block


# 4. Mocked Decision Contract Tests (Section 6 & 9)
def test_mocked_confirmed_with_valid_quote():
    candidate = {
        "detail_id": 201,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный 100 Вт.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 201,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Светильник уличный 100 Вт.",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Уличный светильник",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "CONFIRMED"
    assert res["confidence"] == 0.95
    assert res["validator_version"] == "v4"
    assert res["validation_method"] == "QWEN_CONTEXT_V4"
    assert res["supporting_quote"] == "Светильник уличный 100 Вт."


def test_mocked_rejected_person_title_decision():
    """Test A: Person / FIO / Title / Admin fragment MUST be REJECTED, not UNKNOWN."""
    candidate = {
        "detail_id": 202,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "директор",
        "matched_line": "Заместитель директора А.А. Захаров.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 202,
            "decision": "REJECTED",
            "confidence": 0.90,
            "supporting_quote": "Заместитель директора А.А. Захаров.",
            "reason_code": "ORGANIZATION_NAME_ONLY",
            "reason": "ФИО и должность административного лица",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "REJECTED"
    assert res["confidence"] == 0.90
    assert res["supporting_quote"] == "Заместитель директора А.А. Захаров."
    assert res["reason_code"] == "ORGANIZATION_NAME_ONLY"


def test_mocked_unknown_genuine_ambiguous_decision():
    """Test B: Genuinely ambiguous documentary fragment yields UNKNOWN."""
    candidate = {
        "detail_id": 203,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "раздел",
        "matched_line": "Раздел 4.2. Позиция 12.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 203,
            "decision": "UNKNOWN",
            "confidence": 0.0,
            "supporting_quote": "",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "reason": "Фрагмент не содержит предметного описания товара или работы",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["confidence"] == 0.0
    assert res["supporting_quote"] == ""


def test_mocked_confirmed_missing_quote_demoted():
    candidate = {
        "detail_id": 204,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный 100 Вт.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 204,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "",
            "reason": "No quote provided",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "MISSING_SUPPORTING_QUOTE"


def test_mocked_rejected_hallucinated_quote_demoted():
    candidate = {
        "detail_id": 205,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный 100 Вт.",
    }

    def mock_caller(p):
        return json.dumps({
            "detail_id": 205,
            "decision": "REJECTED",
            "confidence": 0.90,
            "supporting_quote": "Выдуманная цитата которой нет в документе",
            "reason": "Hallucinated quote",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "HALLUCINATED_QUOTE"


# 5. Strict V4 Evidence Provenance Isolation
def test_strict_v4_evidence_provenance():
    mock_conn = MockConnection()

    mock_conn.cursor_obj.fetch_data = [
        {"score": 95.0, "queue_id": 1, "validator_version": "v4", "validation_method": "QWEN_CONTEXT_V4"},
        {"score": 90.0, "queue_id": 1, "validator_version": "v3", "validation_method": "QWEN_CONTEXT_V3"},
        {"score": 85.0, "queue_id": 1, "validator_version": "v2", "validation_method": "QWEN_CONTEXT_V2"},
    ]
    rebuild_affected_evidence(mock_conn, {(100, "lighting")})
    query = mock_conn.cursor_obj.last_query
    assert "INSERT INTO document_evidence" in query
    params = mock_conn.cursor_obj.last_params
    assert params[7] == "v4"  # validator_version
    assert params[8] == "QWEN_CONTEXT_V4"  # validation_method


# 6. Service Batch Binding Regression Test
def test_validator_instance_and_module_validate_candidates_binding():
    c1 = {
        "detail_id": 301,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный 100 Вт.",
    }
    c2 = {
        "detail_id": 302,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "директор",
        "matched_line": "Заместитель директора А.А. Захаров.",
    }

    def mock_caller(p):
        if "директор" in p:
            return json.dumps({
                "detail_id": 302,
                "decision": "REJECTED",
                "confidence": 0.90,
                "supporting_quote": "Заместитель директора А.А. Захаров.",
                "reason_code": "ORGANIZATION_NAME_ONLY",
                "reason": "ФИО и должность административного лица",
            })
        return json.dumps({
            "detail_id": 301,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Светильник уличный 100 Вт.",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Уличный светильник",
        })

    validator = ContextValidator(ai_caller=mock_caller)

    # 1. Instance method check (called by service process_batch)
    assert hasattr(validator, "validate_candidates"), "ContextValidator instance must have validate_candidates method!"
    res_instance = validator.validate_candidates([c1, c2])

    assert len(res_instance) == 2
    assert res_instance[0]["detail_id"] == 301
    assert res_instance[0]["decision"] == "CONFIRMED"
    assert res_instance[0]["supporting_quote"] == "Светильник уличный 100 Вт."
    assert res_instance[1]["detail_id"] == 302
    assert res_instance[1]["decision"] == "REJECTED"
    assert res_instance[1]["supporting_quote"] == "Заместитель директора А.А. Захаров."

    # 2. Module-level helper check
    res_module = validate_candidates([c1, c2], validator=validator)
    assert len(res_module) == 2
    assert res_module[0]["decision"] == "CONFIRMED"
    assert res_module[1]["decision"] == "REJECTED"
