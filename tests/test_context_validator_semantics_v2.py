"""Deterministic regression & static audit tests for Context Validator Semantics V2 (R3-4E).

Validates:
- Taxonomy-agnostic decision policy
- Brand/Manufacturer/Model are NOT mandatory for CONFIRMED
- Contaminated canary tokens are completely absent from production prompt
- Category & subcategory immutability preserved
- Search score/method is not factual authority
- Fail-closed defaults & quote verification
- Provenance attributes set to v2 / QWEN_CONTEXT_V2
"""

import json
import pytest
import sys
import os
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    SYSTEM_PROMPT,
    VALIDATOR_NAME,
    VALIDATOR_VERSION,
    VALIDATION_METHOD,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
    hydrate_candidate_context,
)
from tender_documents_research.document_processor.context_validator_service import (
    update_candidate_validations,
    rebuild_affected_evidence,
)


def _make_candidate(category_code, subcategory_code, matched_term, matched_line, **kwargs):
    c = {
        "detail_id": 101,
        "procurement_id": 555,
        "category_code": category_code,
        "subcategory_code": subcategory_code,
        "matched_term": matched_term,
        "matched_line": matched_line,
        "score": 100.0,
        "match_method": "EXACT",
        "context_before": ["Предмет закупки:"],
        "context_after": ["Доставка на объект."],
        "document_name": "test_spec.pdf",
    }
    c.update(kwargs)
    return c


# ============================================================
# Section 18: Prompt Static Audit Test
# ============================================================
def test_prompt_static_audit():
    """Verifies SYSTEM_PROMPT contains v2 semantic rules and 0 contaminated canary tokens."""
    # 1. Assert semantic statement that brand/manufacturer are not mandatory
    assert "НЕ ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ" in SYSTEM_PROMPT
    assert "бренда" in SYSTEM_PROMPT or "производителя" in SYSTEM_PROMPT

    # 2. Contaminated canary tokens that MUST be absent
    contaminated_canaries = [
        "Денстоп",
        "Пенетрон",
        "MasterTop",
        "MasterEmaco",
        "Техноэласт",
        "Пластфоил",
        "ДКУ",
        "директор",
        "плотина",
        "medical syringe",
    ]

    found_tokens = [tok for tok in contaminated_canaries if tok.lower() in SYSTEM_PROMPT.lower()]
    assert len(found_tokens) == 0, f"Contaminated canary tokens found in SYSTEM_PROMPT: {found_tokens}"


# ============================================================
# Section 17 & 19: Multi-Category Deterministic Semantics Tests
# ============================================================

# Test A: Generic explicit lighting specification without manufacturer/brand/model
def test_generic_lighting_without_brand_confirmed():
    c = _make_candidate(
        category_code="lighting",
        subcategory_code="road_street",
        matched_term="светильник",
        matched_line="Светильник светодиодный, 40 Вт, 2500 лм, IP65, 120 шт.",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Светильник светодиодный, 40 Вт, 2500 лм, IP65, 120 шт.",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Явная спецификация светодиодного светильника с характеристиками",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "CONFIRMED"
    assert res["confidence"] >= 0.80
    assert res["validator_version"] in ("v2", "v4")
    assert res["validation_method"] in ("QWEN_CONTEXT_V2", "QWEN_CONTEXT_V4")


# Test B: Generic explicit flooring requirement without brand
def test_generic_flooring_without_brand_confirmed():
    c = _make_candidate(
        category_code="flooring",
        subcategory_code="epoxy",
        matched_term="покрытие пола",
        matched_line="Устройство эпоксидного покрытия пола толщиной 2 мм",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Устройство эпоксидного покрытия пола толщиной 2 мм",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Сметная расценка на устройство эпоксидного пола",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "CONFIRMED"
    assert res["validator_version"] in ("v2", "v4")


# Test C: Generic explicit technology/work without brand (Injection)
def test_generic_technology_without_brand_confirmed():
    c = _make_candidate(
        category_code="waterproofing",
        subcategory_code="injection",
        matched_term="инъектирование",
        matched_line="Инъектирование трещин полиуретановым составом",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Инъектирование трещин полиуретановым составом",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Технологический процесс инъектирования со строительным материалом",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "CONFIRMED"


# Test C2: Concrete repair category without brand
def test_generic_concrete_repair_without_brand_confirmed():
    c = _make_candidate(
        category_code="concrete_repair",
        subcategory_code="thixotropic",
        matched_term="ремонтный состав",
        matched_line="Ремонтный тиксотропный состав для бетона кл. R4",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.90,
            "supporting_quote": "Ремонтный тиксотропный состав для бетона кл. R4",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Тиксотропный ремонтный состав класса R4",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "CONFIRMED"


# Test D: Isolated ambiguous generic term -> UNKNOWN
def test_isolated_ambiguous_term_unknown():
    c = _make_candidate(
        category_code="waterproofing",
        subcategory_code="membranes",
        matched_term="мембрана",
        matched_line="мембрана",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "UNKNOWN",
            "confidence": 0.0,
            "supporting_quote": "",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "reason": "Одиночное слово мембрана без марки и без области применения",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "UNKNOWN"
    assert res["confidence"] == 0.0


# Test E: Clearly unrelated lexical/context case -> REJECTED
def test_clearly_unrelated_rejected():
    c = _make_candidate(
        category_code="waterproofing",
        subcategory_code="membranes",
        matched_term="проспект",
        matched_line="Адрес поставки: г. Москва, проспект Мира, д. 1",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "REJECTED",
            "confidence": 0.95,
            "supporting_quote": "г. Москва, проспект Мира, д. 1",
            "reason_code": "ADDRESS_OR_LOCATION_ONLY",
            "reason": "Название улицы/проспекта в адресе",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "REJECTED"


# Test G & H: Search score=100 and match_method=EXACT are NOT authority over UNKNOWN model decision
def test_score_and_exact_method_not_authority():
    c = _make_candidate(
        category_code="lighting",
        subcategory_code="road_street",
        matched_term="светильник",
        matched_line="светильник",
        score=100.0,
        match_method="EXACT",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "UNKNOWN",
            "confidence": 0.0,
            "supporting_quote": "",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "reason": "Одиночное слово без спецификации",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "UNKNOWN", "score=100 and EXACT method must NOT force CONFIRMED"


# Test I: Hallucinated supporting quote -> UNKNOWN
def test_hallucinated_quote_demoted_to_unknown():
    c = _make_candidate(
        category_code="lighting",
        subcategory_code="road_street",
        matched_term="светильник",
        matched_line="Светильник консольный 100 Вт",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "Светильник Philips БРЕНД НЕ СУЩЕСТВУЕТ В ТЕКСТЕ",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Выдуманная цитата",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "HALLUCINATED_QUOTE"


# Test J: Model attempts recategorization -> stored original category/subcategory retained
def test_model_recategorization_ignored():
    c = _make_candidate(
        category_code="flooring",
        subcategory_code="epoxy",
        matched_term="покрытие",
        matched_line="Эпоксидный пол 2 мм",
    )

    def mock_ai(prompt):
        return json.dumps({
            "detail_id": 101,
            "category_code": "waterproofing",  # Model attempts to recategorize!
            "subcategory_code": "membranes",
            "decision": "CONFIRMED",
            "confidence": 0.90,
            "supporting_quote": "Эпоксидный пол 2 мм",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
        })

    validator = ContextValidator(ai_caller=mock_ai)
    res = validator.validate_single(c)

    assert res["category_code"] == "flooring", "Original category MUST be immutable"
    assert res["subcategory_code"] == "epoxy", "Original subcategory MUST be immutable"


# Test K: Model failure -> UNKNOWN
def test_model_failure_default_unknown():
    def failing_ai(prompt):
        raise ConnectionError("Ollama host unreachable")

    validator = ContextValidator(ai_caller=failing_ai)
    c = _make_candidate("lighting", "road_street", "светильник", "Светильник ДКУ 50 Вт")
    res = validator.validate_single(c)

    assert res["decision"] == "UNKNOWN"
    assert res["confidence"] == 0.0
    assert res["reason_code"] == "MODEL_EXCEPTION"


# Test L: Provenance constants
def test_v2_provenance_attributes():
    c = _make_candidate("lighting", "road_street", "светильник", "Светильник 40 Вт")
    validator = ContextValidator(ai_caller=lambda p: json.dumps({"decision": "UNKNOWN"}))
    res = validator.validate_single(c)

    assert res["validator_name"] == VALIDATOR_NAME == "context_validator"
    assert res["validator_version"] == VALIDATOR_VERSION
    assert res["validation_method"] == VALIDATION_METHOD
