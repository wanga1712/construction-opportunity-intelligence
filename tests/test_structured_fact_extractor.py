"""
Unit & Integration Tests for R4 Structured Fact Extractor V1 & Taxonomy/Schema Closure.
Coverage includes:
- Test scenarios A through Q from Section 25.
- New taxonomy lookup tests (real snapshot shape, TaxonomySubcategory, unknown fallback, structural error assertion).
- Entity type tests (missing entity_type, null entity_type, unsupported entity_type, malformed product_name).
- Optional core field shape tests (string/list instead of dict, orphan quotes, orphan units).
- Attribute shape tests (dict/string instead of list, malformed attribute shape).
- Parser exception boundary safety (no uncaught AttributeError/TypeError/KeyError).
- Storage regression test with transaction rollback fixture.
"""

import json
import pytest
from typing import Dict, Any, Tuple
from dataclasses import dataclass, field

from tender_documents_research.document_processor.structured_fact_contract import (
    ExtractionRun,
    StructuredEntity,
    StructuredFieldEvidence,
    StructuredAttribute,
    compute_sha256,
)
from tender_documents_research.document_processor.structured_fact_extractor import (
    StructuredFactExtractor,
    STRUCTURED_EXTRACTOR_MODEL,
)
from tender_documents_research.document_processor.crm_taxonomy_loader import (
    TaxonomySnapshot,
    TaxonomySubcategory,
)
from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.structured_fact_repository import (
    save_extraction_run,
    get_extraction_run_by_detail,
)

def make_valid_candidate(snapshot: str) -> Dict[str, Any]:
    sha = compute_sha256(snapshot)
    return {
        "detail_id": 999501,
        "match_id": 888501,
        "procurement_id": 777501,
        "queue_id": 666501,
        "category_code": "lighting",
        "subcategory_code": "office_admin",
        "validation_status": "CONFIRMED",
        "source_validator_name": "context_validator",
        "source_validator_version": "v4",
        "source_validation_method": "QWEN_CONTEXT_V4",
        "source_text_snapshot": snapshot,
        "source_text_sha256": sha,
        "source_available": True,
        "extraction_eligible": True,
    }

def make_mock_ai_caller(response_json: Any, model_name: str = "qwen2.5:7b"):
    def mock_caller(prompt: str, model: str = "qwen2.5:7b", format_json: bool = True) -> Tuple[str, Dict[str, Any]]:
        text = response_json if isinstance(response_json, str) else json.dumps(response_json)
        return (text, {"model": model_name})
    return mock_caller

# 1. Taxonomy Lookup Unit Tests
class FakeTaxonomyLoader:
    def __init__(self, snapshot: Any):
        self.snapshot = snapshot
    def load_snapshot(self):
        return self.snapshot

def test_taxonomy_lookup_real_snapshot_shape():
    subcat = TaxonomySubcategory(
        category_code="lighting",
        category_name="Освещение",
        subcategory_code="office_admin",
        subcategory_name="Офисное освещение"
    )
    fake_snapshot = TaxonomySnapshot(
        contour_code="procurement",
        categories={
            "lighting": {
                "category_code": "lighting",
                "category_name": "Освещение",
                "subcategories": {
                    "office_admin": subcat
                }
            }
        },
        terms=[]
    )
    loader = FakeTaxonomyLoader(fake_snapshot)
    extractor = StructuredFactExtractor(taxonomy_loader=loader)
    
    cat_name, subcat_name = extractor.get_category_names("lighting", "office_admin")
    assert cat_name == "Освещение"
    assert subcat_name == "Офисное освещение"

    prompt = extractor.build_prompt("lighting", "office_admin", "Test snapshot")
    assert "Освещение" in prompt
    assert "lighting" in prompt
    assert "Офисное освещение" in prompt
    assert "office_admin" in prompt

def test_taxonomy_lookup_unknown_fallback():
    fake_snapshot = TaxonomySnapshot(
        contour_code="procurement",
        categories={},
        terms=[]
    )
    loader = FakeTaxonomyLoader(fake_snapshot)
    extractor = StructuredFactExtractor(taxonomy_loader=loader)
    
    cat_name, subcat_name = extractor.get_category_names("unknown_cat", "unknown_sub")
    assert cat_name == "unknown_cat"
    assert subcat_name == "unknown_sub"

def test_taxonomy_lookup_broken_structure_raises():
    # Broken category dict missing "category_name" key -> must NOT be silently swallowed!
    fake_snapshot = TaxonomySnapshot(
        contour_code="procurement",
        categories={
            "lighting": {
                "category_code": "lighting"
                # Missing "category_name"!
            }
        },
        terms=[]
    )
    loader = FakeTaxonomyLoader(fake_snapshot)
    extractor = StructuredFactExtractor(taxonomy_loader=loader)
    
    with pytest.raises(KeyError):
        extractor.get_category_names("lighting")

# 2. Entity Type Fail-Closed Tests
def test_missing_entity_type_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                # Missing entity_type!
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"}
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "MISSING_ENTITY_TYPE"

def test_null_or_unsupported_entity_type_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    
    resp_null = {
        "entities": [
            {
                "entity_type": None,
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"}
            }
        ]
    }
    extractor1 = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp_null))
    assert extractor1.extract_candidate(cand).error_code == "MISSING_ENTITY_TYPE"

    resp_unsupported = {
        "entities": [
            {
                "entity_type": "SOMETHING_INVALID",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"}
            }
        ]
    }
    extractor2 = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp_unsupported))
    assert extractor2.extract_candidate(cand).error_code == "UNSUPPORTED_ENTITY_TYPE"

def test_product_name_wrong_shape_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": "Светильник ДКУ-100"  # String instead of dict!
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "INVALID_PRODUCT_NAME_SHAPE"

# 3. Optional Core Field Shape & Coherence Tests
def test_optional_field_wrong_shape_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "manufacturer": "ООО Вартон"  # String instead of dict!
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "INVALID_MANUFACTURER_SHAPE"

def test_orphan_quote_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "manufacturer": {"raw": None, "quote": "Светильник ДКУ-100"}  # Orphan quote!
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "ORPHAN_QUOTE_MANUFACTURER"

def test_orphan_unit_quantity_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "quantity": {"raw": None, "unit_raw": "шт", "quote": None}  # Orphan unit!
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "ORPHAN_UNIT_QUANTITY"

# 4. Attribute Shape Tests
def test_attributes_wrong_shape_invalid():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    
    # attributes dict instead of list!
    resp1 = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "attributes": {"name": "Мощность", "raw_value": "40 Вт"}
            }
        ]
    }
    extractor1 = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp1))
    assert extractor1.extract_candidate(cand).error_code == "INVALID_ATTRIBUTES_SHAPE"

    # attribute inside list is int instead of dict!
    resp2 = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "attributes": [123]
            }
        ]
    }
    extractor2 = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp2))
    assert extractor2.extract_candidate(cand).error_code == "INVALID_ATTRIBUTE_SHAPE"

# 5. Parser Exception Boundary Test
def test_parser_exception_boundary():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    # Extremely weird payload that might trigger Python exceptions
    resp = {
        "entities": "NOT_A_LIST"
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    # Must NOT raise exception!
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "INVALID_SCHEMA"

# 6. Regressions (Scenarios A-Q)
def test_scenario_a_product_name_only():
    snapshot = "Светильник светодиодный ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник светодиодный ДКУ-100", "quote": "Светильник светодиодный ДКУ-100"},
                "manufacturer": None, "brand": None, "product_line": None, "model_article": None,
                "quantity": None, "unit_price": None, "total_price": None, "currency": None, "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert len(run.entities) == 1
    assert run.entities[0].product_name_raw == "Светильник светодиодный ДКУ-100"

def test_scenario_b_full_product():
    snapshot = "Светильник ДКУ-100, Изготовитель: ООО Вартон, Бренд: VARTON, Модель: 40-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "manufacturer": {"raw": "ООО Вартон", "quote": "Изготовитель: ООО Вартон"},
                "brand": {"raw": "VARTON", "quote": "Бренд: VARTON"},
                "product_line": None,
                "model_article": {"raw": "40-100", "quote": "Модель: 40-100"},
                "quantity": None, "unit_price": None, "total_price": None, "currency": None, "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert run.entities[0].manufacturer_raw == "ООО Вартон"

def test_scenario_c_multiple_entities():
    snapshot = "Светильник ДКУ-100 10 шт. Кабель ВВГнг 50 м"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "quantity": {"raw": "10 шт", "unit_raw": "шт", "quote": "10 шт."},
                "attributes": []
            },
            {
                "entity_type": "MATERIAL",
                "product_name": {"raw": "Кабель ВВГнг", "quote": "Кабель ВВГнг"},
                "quantity": {"raw": "50 м", "unit_raw": "м", "quote": "50 м"},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert len(run.entities) == 2

def test_scenario_d_work_entity():
    snapshot = "Монтаж светильников ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "WORK",
                "product_name": {"raw": "Монтаж светильников ДКУ-100", "quote": "Монтаж светильников ДКУ-100"},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert run.entities[0].entity_type == "WORK"

def test_scenario_e_empty_entities():
    snapshot = "Общие условия поставки товара"
    cand = make_valid_candidate(snapshot)
    resp = {"entities": []}
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "EMPTY"
    assert len(run.entities) == 0

def test_scenario_f_hallucinated_quote():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "manufacturer": {"raw": "ООО Вартон", "quote": "Изготовитель: ООО НесуществующийВартон"},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"

def test_scenario_g_value_not_in_quote():
    snapshot = "Светильник ДКУ-100, Изготовитель: ООО Вартон"
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "manufacturer": {"raw": "АО Светотехника", "quote": "Изготовитель: ООО Вартон"},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"

def test_scenario_h_quantity_deterministic():
    snapshot = "Светильник ДКУ-100, Кол-во: 10 шт."
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "quantity": {"raw": "10 шт", "unit_raw": "шт", "quote": "Кол-во: 10 шт."},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert run.entities[0].quantity_value == 10.0

def test_scenario_i_quantity_ambiguous():
    snapshot = "Светильник ДКУ-100, Кол-во: 10 и 20 шт."
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "quantity": {"raw": "10 и 20 шт", "unit_raw": "шт", "quote": "Кол-во: 10 и 20 шт."},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert run.entities[0].quantity_value is None

def test_scenario_j_price_deterministic():
    snapshot = "Светильник ДКУ-100, Цена: 4 500,00 руб."
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "unit_price": {"raw": "4 500,00 руб.", "quote": "Цена: 4 500,00 руб."},
                "currency": {"raw": "руб.", "quote": "Цена: 4 500,00 руб."},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert run.entities[0].unit_price_value == 4500.0

def test_scenario_k_l_currency():
    snapshot = "Светильник ДКУ-100, Цена: 4500 руб."
    cand = make_valid_candidate(snapshot)
    resp = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "currency": {"raw": "руб.", "quote": "Цена: 4500 руб."},
                "attributes": []
            }
        ]
    }
    extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
    run = extractor.extract_candidate(cand)
    assert run.status == "COMPLETE"
    assert run.entities[0].currency_code == "RUB"

def test_scenario_m_n_attribute():
    snapshot = "Светильник ДКУ-100, Мощность: 40 Вт"
    cand = make_valid_candidate(snapshot)
    resp_valid = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "attributes": [
                    {"name": "Мощность", "raw_value": "40 Вт", "unit_raw": "Вт", "quote": "Мощность: 40 Вт"}
                ]
            }
        ]
    }
    extractor1 = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp_valid))
    run1 = extractor1.extract_candidate(cand)
    assert run1.status == "COMPLETE"
    assert run1.entities[0].attributes[0].numeric_value == 40.0

    resp_mismatch = {
        "entities": [
            {
                "entity_type": "PRODUCT",
                "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                "attributes": [
                    {"name": "Мощность", "raw_value": "40 Вт", "unit_raw": "Вт", "quote": "Несуществующая цитата"}
                ]
            }
        ]
    }
    extractor2 = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp_mismatch))
    run2 = extractor2.extract_candidate(cand)
    assert run2.status == "ERROR"

def test_scenario_o_wrong_model():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    resp = {"entities": []}
    wrong_caller = make_mock_ai_caller(resp, model_name="llama3:latest")
    extractor = StructuredFactExtractor(ai_caller=wrong_caller)
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "WRONG_MODEL"

def test_scenario_p_invalid_json():
    snapshot = "Светильник ДКУ-100"
    cand = make_valid_candidate(snapshot)
    def bad_json_caller(prompt: str, model: str = "qwen2.5:7b", format_json: bool = True):
        return ("NOT VALID JSON text", {"model": "qwen2.5:7b"})
    extractor = StructuredFactExtractor(ai_caller=bad_json_caller)
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "INVALID_JSON"

def test_scenario_q_source_unavailable_zero_model_call():
    cand = {
        "detail_id": 999502,
        "validation_status": "REJECTED",
        "source_available": False,
        "extraction_eligible": False,
    }
    called = False
    def spy_caller(prompt: str, model: str = "qwen2.5:7b", format_json: bool = True):
        nonlocal called
        called = True
        return ("{}", {"model": "qwen2.5:7b"})
    
    extractor = StructuredFactExtractor(ai_caller=spy_caller)
    run = extractor.extract_candidate(cand)
    assert run.status == "ERROR"
    assert run.error_code == "INVALID_INPUT_AUTHORITY"
    assert called is False

def test_storage_regression_transaction_rollback():
    doc_conn = get_doc_db_connection()
    synthetic_detail_id = 9999994
    snapshot = "Светильник ДКУ-100, Изготовитель: ООО Вартон, 10 шт."
    sha = compute_sha256(snapshot)

    try:
        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, 8888894, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id,))

        cand = {
            "detail_id": synthetic_detail_id,
            "procurement_id": 8888894,
            "category_code": "lighting",
            "validation_status": "CONFIRMED",
            "source_validator_name": "context_validator",
            "source_validator_version": "v4",
            "source_validation_method": "QWEN_CONTEXT_V4",
            "source_text_snapshot": snapshot,
            "source_text_sha256": sha,
            "source_available": True,
            "extraction_eligible": True,
        }
        resp = {
            "entities": [
                {
                    "entity_type": "PRODUCT",
                    "product_name": {"raw": "Светильник ДКУ-100", "quote": "Светильник ДКУ-100"},
                    "manufacturer": {"raw": "ООО Вартон", "quote": "Изготовитель: ООО Вартон"},
                    "quantity": {"raw": "10 шт", "unit_raw": "шт", "quote": "10 шт."},
                    "attributes": []
                }
            ]
        }
        extractor = StructuredFactExtractor(ai_caller=make_mock_ai_caller(resp))
        run = extractor.extract_candidate(cand)
        assert run.status == "COMPLETE"

        run_id = save_extraction_run(doc_conn, run)
        assert run_id > 0

        saved_run = get_extraction_run_by_detail(doc_conn, synthetic_detail_id)
        assert saved_run is not None
        assert saved_run.source_text_sha256 == sha
        assert saved_run.status == "COMPLETE"
        assert len(saved_run.entities) == 1
        assert saved_run.entities[0].quantity_value == 10.0
    finally:
        doc_conn.rollback()

    with doc_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_match_details WHERE id = %s", (synthetic_detail_id,))
        assert cur.fetchone()[0] == 0
    doc_conn.close()
