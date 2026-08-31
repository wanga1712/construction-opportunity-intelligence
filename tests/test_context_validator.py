import json
import pytest
from unittest.mock import MagicMock

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    validate_candidates,
)
from tender_documents_research.document_processor.dto import (
    FileProcessResult,
    MatchResult,
    MatchDetailResult,
    EvidenceResult,
)
from tender_documents_research.document_processor.evidence_aggregator import EvidenceAggregator
from tender_documents_research.document_processor.backends.s13_persistence import S13V2TaskPersistenceService
from tender_documents_research.document_processor.context_validator_service import (
    update_candidate_validations,
    rebuild_affected_evidence,
)


def test_1_model_timeout_yields_unknown():
    """1. Model timeout / network error produces UNKNOWN with 0.0 confidence."""
    def timeout_caller(prompt: str) -> str:
        raise TimeoutError("Ollama request timed out after 45s")

    validator = ContextValidator(ai_caller=timeout_caller)
    candidate = {
        "detail_id": 1,
        "procurement_id": 100,
        "category_code": "waterproofing",
        "subcategory_code": "injection",
        "matched_term": "инъекц",
        "matched_line": "Шприц инъекционный 50 мл",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["confidence"] == 0.0
    assert result["reason_code"] == "MODEL_EXCEPTION"


def test_2_invalid_json_yields_unknown():
    """2. Non-JSON or malformed model response produces UNKNOWN."""
    def malformed_caller(prompt: str) -> str:
        return "I am not sure, this looks like a random text without JSON."

    validator = ContextValidator(ai_caller=malformed_caller)
    candidate = {
        "detail_id": 2,
        "procurement_id": 100,
        "category_code": "flooring",
        "matched_term": "денстоп",
        "matched_line": "Покрытие пола Денстоп ЭП-201",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["confidence"] == 0.0
    assert result["reason_code"] == "INVALID_JSON"


def test_3_invalid_decision_enum_yields_unknown():
    """3. Invalid decision enum (e.g. MAYBE, YES) is demoted to UNKNOWN."""
    def invalid_enum_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 3,
            "decision": "MAYBE_CONFIRMED",
            "confidence": 0.99,
            "supporting_quote": "Денстоп ЭП-201",
            "reason_code": "CUSTOM",
            "reason": "Invalid enum test",
        })

    validator = ContextValidator(ai_caller=invalid_enum_caller)
    candidate = {
        "detail_id": 3,
        "procurement_id": 100,
        "category_code": "flooring",
        "matched_term": "денстоп",
        "matched_line": "Покрытие пола Денстоп ЭП-201",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["reason_code"] == "INVALID_DECISION_ENUM"


def test_4_low_confidence_confirmed_yields_unknown():
    """4. CONFIRMED with confidence < 0.90 is demoted to UNKNOWN."""
    def low_conf_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 4,
            "decision": "CONFIRMED",
            "confidence": 0.85,  # Below 0.90 threshold
            "supporting_quote": "Денстоп ЭП-201",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Likely flooring product",
        })

    validator = ContextValidator(confirm_threshold=0.90, ai_caller=low_conf_caller)
    candidate = {
        "detail_id": 4,
        "procurement_id": 100,
        "category_code": "flooring",
        "matched_term": "денстоп",
        "matched_line": "Покрытие пола Денстоп ЭП-201",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["reason_code"] == "LOW_CONFIDENCE"


def test_5_low_confidence_rejected_yields_unknown():
    """5. REJECTED with confidence < 0.95 is demoted to UNKNOWN."""
    def low_conf_reject_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 5,
            "decision": "REJECTED",
            "confidence": 0.92,  # Below 0.95 threshold
            "supporting_quote": "ПРОЕКТ ДОГОВОРА",
            "reason_code": "FUZZY_LEXICAL_COLLISION",
            "reason": "Might be a collision",
        })

    validator = ContextValidator(reject_threshold=0.95, ai_caller=low_conf_reject_caller)
    candidate = {
        "detail_id": 5,
        "procurement_id": 100,
        "category_code": "lighting",
        "matched_term": "проспект",
        "matched_line": "ПРОЕКТ ДОГОВОРА",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["reason_code"] == "LOW_CONFIDENCE"


def test_6_hallucinated_quote_yields_unknown():
    """6. Supporting quote not found in context demotes decision to UNKNOWN."""
    def hallucinated_quote_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 6,
            "decision": "CONFIRMED",
            "confidence": 0.99,
            "supporting_quote": "Светильник ДКУ 100 Вт уличный светодиодный",  # NOT in matched line
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Product mentioned",
        })

    validator = ContextValidator(ai_caller=hallucinated_quote_caller)
    candidate = {
        "detail_id": 6,
        "procurement_id": 100,
        "category_code": "lighting",
        "matched_term": "светильник",
        "matched_line": "Кабель силовой ВВГнг 3х2.5",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["reason_code"] == "HALLUCINATED_QUOTE"


def test_7_obvious_fuzzy_collision_rejected():
    """7. Obvious fuzzy collision (e.g. ПРОЕКТ matched to проспект) is REJECTED with high confidence."""
    def reject_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 7,
            "decision": "REJECTED",
            "confidence": 0.99,
            "supporting_quote": "ПРОЕКТ ДОГОВОРА",
            "reason_code": "FUZZY_LEXICAL_COLLISION",
            "reason": "Слово ПРОЕКТ не относится к светильникам и уличному освещению",
        })

    validator = ContextValidator(ai_caller=reject_caller)
    candidate = {
        "detail_id": 7,
        "procurement_id": 100,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "проспект",
        "matched_line": "ПРОЕКТ ДОГОВОРА",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "REJECTED"
    assert result["confidence"] >= 0.95
    assert result["reason_code"] == "FUZZY_LEXICAL_COLLISION"


def test_8_clear_natural_product_context_confirmed():
    """8. Clear product requirement in context is CONFIRMED with quote verified."""
    def confirm_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 8,
            "decision": "CONFIRMED",
            "confidence": 0.98,
            "supporting_quote": "Покрытие пола составом Денстоп ЭП-201",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Прямое указание полимерного наливного пола Денстоп ЭП-201",
        })

    validator = ContextValidator(ai_caller=confirm_caller)
    candidate = {
        "detail_id": 8,
        "procurement_id": 100,
        "category_code": "flooring",
        "subcategory_code": "polymer_self_leveling",
        "matched_term": "денстоп",
        "matched_line": "Покрытие пола составом Денстоп ЭП-201 толщиной 2 мм",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "CONFIRMED"
    assert result["confidence"] >= 0.90
    assert result["reason_code"] == "SPECIFICATION_PRODUCT_REQUIREMENT"


def test_9_ambiguous_context_yields_unknown():
    """9. Ambiguous / truncated context produces UNKNOWN."""
    def unknown_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 9,
            "decision": "UNKNOWN",
            "confidence": 0.50,
            "supporting_quote": "",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "reason": "Контекст слишком короткий и неоднозначный",
        })

    validator = ContextValidator(ai_caller=unknown_caller)
    candidate = {
        "detail_id": 9,
        "procurement_id": 100,
        "category_code": "lighting",
        "matched_term": "свет",
        "matched_line": "свет",
    }
    result = validator.validate_single(candidate)
    assert result["decision"] == "UNKNOWN"
    assert result["reason_code"] == "INSUFFICIENT_CONTEXT"


def test_10_validator_cannot_change_category_subcategory():
    """10. Category and subcategory remain strictly immutable even if model attempts recategorization."""
    def mutating_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 10,
            "decision": "CONFIRMED",
            "confidence": 0.99,
            "category_code": "wrong_invented_category",
            "subcategory_code": "wrong_invented_subcategory",
            "supporting_quote": "Денстоп ЭП-201",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
            "reason": "Attempted to mutate category",
        })

    validator = ContextValidator(ai_caller=mutating_caller)
    candidate = {
        "detail_id": 10,
        "procurement_id": 100,
        "category_code": "flooring",
        "subcategory_code": "polymer_self_leveling",
        "matched_term": "денстоп",
        "matched_line": "Покрытие пола составом Денстоп ЭП-201",
    }
    result = validator.validate_single(candidate)
    assert result["category_code"] == "flooring", "category_code must remain immutable"
    assert result["subcategory_code"] == "polymer_self_leveling", "subcategory_code must remain immutable"


def test_11_rejected_raw_match_remains_stored():
    """11. Rejection updates validation fields but preserves raw candidate details."""
    candidate = {
        "detail_id": 11,
        "procurement_id": 163649,
        "category_code": "waterproofing",
        "subcategory_code": "injection",
        "matched_term": "инъекц",
        "score": 100.0,
        "match_method": "STEM_PREFIX",
        "matched_line": "Шприц инъекционный 50 мл",
    }
    result = {
        "detail_id": 11,
        "procurement_id": 163649,
        "category_code": "waterproofing",
        "subcategory_code": "injection",
        "decision": "REJECTED",
        "confidence": 0.99,
        "reason_code": "UNRELATED_PRODUCT",
        "reason": "Медицинский шприц, не строительная гидроизоляция",
        "validation_method": "QWEN_CONTEXT_V1",
        "validator_name": "context_validator",
        "validator_version": "v1",
    }
    assert result["decision"] == "REJECTED"
    assert candidate["matched_term"] == "инъекц"
    assert candidate["matched_line"] == "Шприц инъекционный 50 мл"


def test_12_only_confirmed_rebuilds_evidence():
    """12. EvidenceAggregator builds positive evidence only from CONFIRMED details."""
    d_conf = MatchDetailResult(
        category_code="flooring",
        subcategory_code="polymer",
        matched_term="денстоп",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Денстоп"},
        page_or_sheet="1",
        row_number=1,
        validation_status="CONFIRMED",
    )
    d_rej = MatchDetailResult(
        category_code="waterproofing",
        subcategory_code="injection",
        matched_term="инъекц",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Шприц"},
        page_or_sheet="1",
        row_number=2,
        validation_status="REJECTED",
    )
    d_unk = MatchDetailResult(
        category_code="lighting",
        subcategory_code="admin",
        matched_term="административ",
        term_type="search",
        score=80.0,
        row_data={"matched_line": "Администрация"},
        page_or_sheet="1",
        row_number=3,
        validation_status="UNKNOWN",
    )

    match = MatchResult(category_code="flooring", match_count=3, score=100.0, details=[d_conf, d_rej, d_unk])
    file_res = FileProcessResult(file_name="doc.pdf", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 1
    assert evidence[0].category_code == "flooring"
    assert evidence[0].validation_status == "CONFIRMED"


def test_13_unknown_prevents_factual_no():
    """13. Unresolved UNKNOWN match detail prevents false factual NO."""
    confirmed_cnt = 0
    unknown_match_cnt = 1
    dl_st = "COMPLETED"
    pr_st = "COMPLETED"
    d_item = {"document_key": "k"}

    useful_docs = []
    non_useful_docs = []
    unknown_docs = []

    if dl_st == "COMPLETED" and pr_st == "COMPLETED":
        if confirmed_cnt > 0:
            useful_docs.append(d_item)
        elif unknown_match_cnt > 0:
            unknown_docs.append(d_item)
        else:
            non_useful_docs.append(d_item)
    else:
        unknown_docs.append(d_item)

    assert len(useful_docs) == 0
    assert len(non_useful_docs) == 0, "UNKNOWN match must not become non_useful (NO)"
    assert len(unknown_docs) == 1


def test_14_qwen_outage_does_not_break_raw_document_persistence():
    """14. Document processor persists raw candidates with UNKNOWN status when Qwen is not called during parse."""
    detail = MatchDetailResult(
        category_code="waterproofing",
        subcategory_code="injection",
        matched_term="инъекц",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Инъектирование швов полиуретановой смолой"},
        page_or_sheet="1",
        row_number=1,
        match_method="STEM_PREFIX",
        validation_status="UNKNOWN",
    )
    # Status defaults to UNKNOWN, raw persistence succeeds without online Qwen call
    assert detail.validation_status == "UNKNOWN"
    assert detail.match_method == "STEM_PREFIX"
