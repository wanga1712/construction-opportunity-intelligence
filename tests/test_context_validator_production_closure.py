import json
import pytest
from unittest.mock import MagicMock, patch

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    validate_candidates,
    SYSTEM_PROMPT,
)
from tender_documents_research.document_processor.context_validator_service import (
    claim_unvalidated_candidates,
    enrich_candidates_with_crm_facts,
    filter_target_candidates,
    update_candidate_validations,
    rebuild_affected_evidence,
    PIPELINE_GENERATION,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import (
    TaxonomySnapshot,
    TaxonomySubcategory,
)
from src.services.commercial_routing_v3.okpd_priors import (
    classify_target_okpd,
    ADMISSION_TARGET,
    ADMISSION_OUT_OF_TARGET,
    ADMISSION_UNKNOWN_OKPD,
)
import tender_documents_research.document_processor.context_validator as cv_module


def test_1_sql_precedence_cross_generation_exclusion():
    """1. SQL query excludes unvalidated rows from other generations."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    claim_unvalidated_candidates(mock_conn, batch_size=25, generation=PIPELINE_GENERATION)

    executed_query = mock_cur.execute.call_args[0][0]
    executed_params = mock_cur.execute.call_args[0][1]

    # Verify query contains parenthesized OR and generation parameter
    norm_query = " ".join(executed_query.split())
    assert "WHERE ( d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL )" in norm_query or "WHERE (d.validation_status IN ('UNKNOWN', 'RAW', 'PENDING') OR d.validation_status IS NULL)" in norm_query
    assert "AND d.pipeline_generation = %s" in norm_query
    assert executed_params[0] == PIPELINE_GENERATION


def test_2_out_of_target_candidate_excluded_from_normal_service():
    """2. Out-of-target candidate is excluded by filter_target_candidates."""
    priors = [
        {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX", "active": True}
    ]
    candidates = [
        {
            "detail_id": 1,
            "procurement_id": 163649,
            "procurement_okpd_code": "32.99.53.191",  # Medical / didactic out of target
            "matched_term": "инъекц",
        }
    ]
    filtered = filter_target_candidates(candidates, priors)
    assert len(filtered) == 0, "Out of target procurement must be filtered out"


def test_3_target_candidate_admitted_to_validator():
    """3. Target candidate is admitted by filter_target_candidates."""
    priors = [
        {"commercial_category_code": "lighting", "okpd_pattern": "27.40", "match_type": "PREFIX", "active": True}
    ]
    candidates = [
        {
            "detail_id": 2,
            "procurement_id": 100,
            "procurement_okpd_code": "27.40.39.000",  # TARGET lighting
            "matched_term": "светильник",
        }
    ]
    filtered = filter_target_candidates(candidates, priors)
    assert len(filtered) == 1
    assert filtered[0]["detail_id"] == 2


def test_4_actual_candidate_enrichment_supplies_okpd_and_title():
    """4. Candidate enrichment attaches procurement OKPD code/name and title from CRM DB."""
    mock_crm_conn = MagicMock()
    mock_cur = MagicMock()
    mock_crm_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [
        {
            "id": 500,
            "auction_name": "Капитальный ремонт кровли",
            "okpd_code": "41.20.40.000",
            "okpd_name": "Работы строительные",
        }
    ]

    snapshot = TaxonomySnapshot(contour_code="procurement", categories={}, terms=[])
    raw_candidates = [{"detail_id": 10, "procurement_id": 500, "category_code": "waterproofing"}]

    enriched = enrich_candidates_with_crm_facts(raw_candidates, mock_crm_conn, snapshot)
    assert len(enriched) == 1
    assert enriched[0]["procurement_title"] == "Капитальный ремонт кровли"
    assert enriched[0]["procurement_okpd_code"] == "41.20.40.000"
    assert enriched[0]["procurement_okpd_name"] == "Работы строительные"


def test_5_actual_candidate_enrichment_supplies_category_and_subcategory_names():
    """5. Candidate enrichment attaches canonical category & subcategory names from taxonomy snapshot."""
    mock_crm_conn = MagicMock()
    mock_cur = MagicMock()
    mock_crm_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    sub = TaxonomySubcategory(
        category_code="flooring",
        category_name="Напольные покрытия",
        subcategory_code="polymer_self_leveling",
        subcategory_name="Полимерные наливные полы",
    )
    categories = {
        "flooring": {
            "category_code": "flooring",
            "category_name": "Напольные покрытия",
            "subcategories": {"polymer_self_leveling": sub},
        }
    }
    snapshot = TaxonomySnapshot(contour_code="procurement", categories=categories, terms=[])
    raw_candidates = [{
        "detail_id": 20,
        "procurement_id": 100,
        "category_code": "flooring",
        "subcategory_code": "polymer_self_leveling",
    }]

    enriched = enrich_candidates_with_crm_facts(raw_candidates, mock_crm_conn, snapshot)
    assert enriched[0]["category_name"] == "Напольные покрытия"
    assert enriched[0]["subcategory_name"] == "Полимерные наливные полы"


def test_6_negative_phrases_supplied_from_exact_source_subcategory():
    """6. Candidate enrichment attaches exact subcategory negative phrases."""
    mock_crm_conn = MagicMock()
    mock_cur = MagicMock()
    mock_crm_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    sub = TaxonomySubcategory(
        category_code="waterproofing",
        category_name="Гидроизоляция",
        subcategory_code="injection",
        subcategory_name="Инъекционная гидроизоляция",
        negative_phrases=["шприц", "игла", "медицинск"],
    )
    categories = {
        "waterproofing": {
            "category_code": "waterproofing",
            "category_name": "Гидроизоляция",
            "subcategories": {"injection": sub},
        }
    }
    snapshot = TaxonomySnapshot(contour_code="procurement", categories=categories, terms=[])
    raw_candidates = [{
        "detail_id": 30,
        "procurement_id": 100,
        "category_code": "waterproofing",
        "subcategory_code": "injection",
    }]

    enriched = enrich_candidates_with_crm_facts(raw_candidates, mock_crm_conn, snapshot)
    assert enriched[0]["negative_phrases"] == ["шприц", "игла", "медицинск"]


def test_7_shared_ai_client_used():
    """7. ContextValidator uses canonical src.services.ai_client."""
    from src.services.ai_client import generate
    assert callable(cv_module.generate)
    assert cv_module.generate == generate


def test_8_duplicate_urllib_ollama_path_absent():
    """8. No direct urllib or duplicate call_ollama HTTP client in context_validator.py."""
    assert not hasattr(cv_module, "call_ollama"), "Duplicate call_ollama must be removed"
    assert "urllib" not in dir(cv_module), "urllib must not be directly imported in context_validator"


def test_9_genuine_ambiguous_yields_unknown():
    """9. Genuine ambiguous / truncated context produces UNKNOWN."""
    def mock_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 99,
            "decision": "UNKNOWN",
            "confidence": 0.50,
            "supporting_quote": "",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "reason": "Контекст обрезан, невозможно определить назначение материала",
        })

    validator = ContextValidator(ai_caller=mock_caller)
    candidate = {
        "detail_id": 99,
        "procurement_id": 100,
        "category_code": "waterproofing",
        "subcategory_code": "penetrating",
        "matched_term": "состав",
        "matched_line": "состав",
    }
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "INSUFFICIENT_CONTEXT"


def test_10_category_immutability_preserved():
    """10. Category and subcategory cannot be altered by validator decision."""
    def rogue_caller(prompt: str) -> str:
        return json.dumps({
            "detail_id": 101,
            "decision": "CONFIRMED",
            "confidence": 0.99,
            "category_code": "invented_cat",
            "subcategory_code": "invented_sub",
            "supporting_quote": "Светильник ДКУ",
            "reason_code": "SPECIFICATION_PRODUCT_REQUIREMENT",
        })

    validator = ContextValidator(ai_caller=rogue_caller)
    candidate = {
        "detail_id": 101,
        "procurement_id": 100,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник ДКУ 100 Вт",
    }
    res = validator.validate_single(candidate)
    assert res["category_code"] == "lighting"
    assert res["subcategory_code"] == "road_street"


def test_11_qwen_failure_yields_unknown():
    """11. Network exception or timeout during model call produces fail-closed UNKNOWN."""
    def error_caller(prompt: str) -> str:
        raise ConnectionResetError("Connection reset by peer")

    validator = ContextValidator(ai_caller=error_caller)
    candidate = {
        "detail_id": 102,
        "procurement_id": 100,
        "category_code": "lighting",
        "matched_term": "светильник",
        "matched_line": "Светильник ДКУ",
    }
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["confidence"] == 0.0
    assert res["reason_code"] == "MODEL_EXCEPTION"


def test_12_only_confirmed_creates_evidence():
    """12. Positive document_evidence is inserted only for CONFIRMED match details."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Case A: 0 confirmed details -> deletes evidence
    mock_cur.fetchall.return_value = []
    rebuild_affected_evidence(mock_conn, {(997, "waterproofing")})
    delete_query = mock_cur.execute.call_args[0][0]
    assert "DELETE FROM document_evidence" in delete_query

    # Case B: confirmed details exist -> inserts CONFIRMED evidence
    mock_cur.fetchall.return_value = [{"score": 85.0, "queue_id": 148265, "validator_version": "v1", "validation_method": "QWEN_CONTEXT_V1"}]
    rebuild_affected_evidence(mock_conn, {(997, "waterproofing")})
    insert_query = mock_cur.execute.call_args[0][0]
    assert "INSERT INTO document_evidence" in insert_query
    assert "'CONFIRMED'" in insert_query
