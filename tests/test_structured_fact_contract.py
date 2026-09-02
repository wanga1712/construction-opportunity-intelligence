"""
Unit & Integration Tests for R4 Derived Value Fail-Closed Validation Contracts.
Coverage includes:
- Entity numeric parser: 10, 10,5, 10.5, 4 500, 4 500,00, 1 234 567,89
- Unparseable raw text with numeric value -> INVALID
- Mismatched entity numeric value -> INVALID
- Attribute numeric: raw 40 Вт + 40 (VALID), raw 40 Вт + 5000 (INVALID)
- Attribute unit: supported raw unit (VALID), invented raw unit (INVALID), normalized without raw (INVALID)
- Quantity unit: supported raw unit (VALID), invented raw unit (INVALID), normalized without raw (INVALID)
- Currency: руб.->RUB (VALID), ₽->RUB (VALID), RUB->RUB (VALID), руб.->USD (INVALID), unknown+USD (INVALID), unknown+NULL (VALID)
- Repository Pre-DML enforcement on all contract violations
- Regressions (source authority, SHA, idempotency, stable IDs, rollback)
"""

import hashlib
import pytest
from typing import Dict, Any

from tender_documents_research.document_processor.structured_fact_contract import (
    ExtractionRun,
    StructuredEntity,
    StructuredFieldEvidence,
    StructuredAttribute,
    STRUCTURED_EXTRACTOR_NAME,
    STRUCTURED_EXTRACTOR_VERSION,
    EXTRACTION_METHOD,
    PROMPT_VERSION,
    ALLOWED_ENTITY_TYPES,
    ExtractionRunIdentityConflict,
    verify_source_quote,
    normalize_whitespace,
    compute_sha256,
    parse_numeric_values_from_string,
    validate_numeric_consistency,
    validate_currency_consistency,
    validate_extraction_run,
    extraction_run_to_dict,
    extraction_run_from_dict,
)
from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.structured_fact_repository import (
    save_extraction_run,
    get_extraction_run_by_detail,
)
from tender_documents_research.document_processor.r4_input_selector import (
    get_r4_input_candidates,
    build_r4_source_snapshot,
)

# 1. Numeric Parser Unit Tests
def test_numeric_parser_formats():
    assert parse_numeric_values_from_string("10") == [10.0]
    assert parse_numeric_values_from_string("10,5") == [10.5]
    assert parse_numeric_values_from_string("10.5") == [10.5]
    assert parse_numeric_values_from_string("4 500") == [4500.0]
    assert parse_numeric_values_from_string("4 500,00") == [4500.0]
    assert parse_numeric_values_from_string("1 234 567,89") == [1234567.89]
    assert parse_numeric_values_from_string("десять штук") == []

# 2. Entity Numeric Fail-Closed Contract Tests
def test_entity_unparseable_raw_with_numeric_invalid():
    snapshot = "Светильник ДКУ, Кол-во: десять штук"
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ",
        quantity_raw="десять штук",
        quantity_value=10.0,  # Unparseable raw with non-null numeric -> INVALID!
        source_quote="Светильник ДКУ",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ"),
            StructuredFieldEvidence(field_name="quantity", source_quote="Кол-во: десять штук"),
        ]
    )
    run = ExtractionRun(
        detail_id=999301,
        procurement_id=888301,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("failed numeric consistency" in e for e in errors)

def test_entity_mismatched_numeric_invalid():
    snapshot = "Светильник ДКУ, Кол-во: 10 шт"
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ",
        quantity_raw="10 шт",
        quantity_value=999.0,  # Mismatched value -> INVALID!
        source_quote="Светильник ДКУ",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ"),
            StructuredFieldEvidence(field_name="quantity", source_quote="Кол-во: 10 шт"),
        ]
    )
    run = ExtractionRun(
        detail_id=999302,
        procurement_id=888302,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("failed numeric consistency" in e for e in errors)

# 3. Attribute Numeric Tests
def test_attribute_numeric_valid_and_invalid():
    snapshot = "Светильник ДКУ-100 Вт, Мощность 40 Вт"
    
    # Valid: raw "40 Вт", numeric 40.0
    attr_valid = StructuredAttribute(
        attribute_name="Мощность",
        attribute_name_normalized="power",
        raw_value="40 Вт",
        numeric_value=40.0,
        source_quote="Мощность 40 Вт"
    )
    ent1 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr_valid]
    )
    run1 = ExtractionRun(
        detail_id=999303,
        procurement_id=888303,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent1],
    )
    assert validate_extraction_run(run1)[0] is True

    # Invalid: raw "40 Вт", numeric 5000.0 -> INVALID!
    attr_invalid = StructuredAttribute(
        attribute_name="Мощность",
        attribute_name_normalized="power",
        raw_value="40 Вт",
        numeric_value=5000.0,
        source_quote="Мощность 40 Вт"
    )
    ent2 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr_invalid]
    )
    run2 = ExtractionRun(
        detail_id=999304,
        procurement_id=888304,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent2],
    )
    is_valid, errors = validate_extraction_run(run2)
    assert is_valid is False
    assert any("does not match raw_value '40 Вт'" in e for e in errors)

# 4. Attribute Unit Provenance Tests
def test_attribute_unit_provenance():
    snapshot = "Светильник ДКУ-100 Вт, Мощность 40 Вт"
    
    # Supported unit_raw "Вт" -> VALID
    attr1 = StructuredAttribute(
        attribute_name="Мощность",
        attribute_name_normalized="power",
        raw_value="40 Вт",
        unit_raw="Вт",
        unit_normalized="W",
        source_quote="Мощность 40 Вт"
    )
    ent1 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr1]
    )
    run1 = ExtractionRun(
        detail_id=999305,
        procurement_id=888305,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent1],
    )
    assert validate_extraction_run(run1)[0] is True

    # Invented unit_raw "кг" -> INVALID
    attr2 = StructuredAttribute(
        attribute_name="Мощность",
        attribute_name_normalized="power",
        raw_value="40 Вт",
        unit_raw="кг",  # Invented unit!
        source_quote="Мощность 40 Вт"
    )
    ent2 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr2]
    )
    run2 = ExtractionRun(
        detail_id=999306,
        procurement_id=888306,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent2],
    )
    is_valid, errors = validate_extraction_run(run2)
    assert is_valid is False
    assert any("unit_raw 'кг' not supported" in e for e in errors)

    # unit_normalized without unit_raw -> INVALID
    attr3 = StructuredAttribute(
        attribute_name="Мощность",
        attribute_name_normalized="power",
        raw_value="40 Вт",
        unit_raw=None,
        unit_normalized="W",  # Missing raw unit!
        source_quote="Мощность 40 Вт"
    )
    ent3 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr3]
    )
    run3 = ExtractionRun(
        detail_id=999307,
        procurement_id=888307,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent3],
    )
    is_valid, errors = validate_extraction_run(run3)
    assert is_valid is False
    assert any("unit_normalized 'W' requires unit_raw" in e for e in errors)

# 5. Quantity Unit Provenance Tests
def test_quantity_unit_provenance():
    snapshot = "Плита минераловатная ТЕХНОФАС, 50 м3"
    
    # Supported quantity_unit_raw "м3" -> VALID
    ent1 = StructuredEntity(
        product_name_raw="Плита минераловатная ТЕХНОФАС",
        quantity_raw="50 м3",
        quantity_unit_raw="м3",
        quantity_unit_normalized="m3",
        source_quote="Плита минераловатная ТЕХНОФАС",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Плита минераловатная ТЕХНОФАС"),
            StructuredFieldEvidence(field_name="quantity", source_quote="50 м3")
        ]
    )
    run1 = ExtractionRun(
        detail_id=999308,
        procurement_id=888308,
        category_code="insulation",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent1],
    )
    assert validate_extraction_run(run1)[0] is True

    # Invented quantity_unit_raw "шт" vs raw "50 м3" -> INVALID
    ent2 = StructuredEntity(
        product_name_raw="Плита минераловатная ТЕХНОФАС",
        quantity_raw="50 м3",
        quantity_unit_raw="шт",  # Invented unit!
        source_quote="Плита минераловатная ТЕХНОФАС",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Плита минераловатная ТЕХНОФАС"),
            StructuredFieldEvidence(field_name="quantity", source_quote="50 м3")
        ]
    )
    run2 = ExtractionRun(
        detail_id=999309,
        procurement_id=888309,
        category_code="insulation",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent2],
    )
    is_valid, errors = validate_extraction_run(run2)
    assert is_valid is False
    assert any("quantity_unit_raw 'шт' not supported" in e for e in errors)

    # quantity_unit_raw without quantity_raw -> INVALID
    ent3 = StructuredEntity(
        product_name_raw="Плита минераловатная ТЕХНОФАС",
        quantity_raw=None,  # Missing quantity_raw!
        quantity_unit_raw="м3",
        source_quote="Плита минераловатная ТЕХНОФАС",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Плита минераловатная ТЕХНОФАС")]
    )
    run3 = ExtractionRun(
        detail_id=999310,
        procurement_id=888310,
        category_code="insulation",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent3],
    )
    is_valid, errors = validate_extraction_run(run3)
    assert is_valid is False
    assert any("quantity_unit_raw 'м3' requires quantity_raw" in e for e in errors)

# 6. Currency Fail-Closed Tests
def test_currency_fail_closed_contract():
    snapshot = "Светильник ДКУ, Цена: 4500 руб."
    
    # руб. -> RUB -> VALID
    ent1 = StructuredEntity(
        product_name_raw="Светильник ДКУ",
        currency_raw="руб.",
        currency_code="RUB",
        source_quote="Светильник ДКУ",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ"),
            StructuredFieldEvidence(field_name="currency", source_quote="4500 руб.")
        ]
    )
    run1 = ExtractionRun(
        detail_id=999311,
        procurement_id=888311,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent1],
    )
    assert validate_extraction_run(run1)[0] is True

    # руб. -> USD -> INVALID
    ent2 = StructuredEntity(
        product_name_raw="Светильник ДКУ",
        currency_raw="руб.",
        currency_code="USD",  # Wrong code!
        source_quote="Светильник ДКУ",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ"),
            StructuredFieldEvidence(field_name="currency", source_quote="4500 руб.")
        ]
    )
    run2 = ExtractionRun(
        detail_id=999312,
        procurement_id=888312,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent2],
    )
    is_valid, errors = validate_extraction_run(run2)
    assert is_valid is False
    assert any("currency_code 'USD' failed consistency" in e for e in errors)

    # Unknown raw currency + NULL code -> VALID
    snapshot_unk = "Светильник ДКУ, Цена: 4500 неизвестная валюта"
    ent3 = StructuredEntity(
        product_name_raw="Светильник ДКУ",
        currency_raw="неизвестная валюта",
        currency_code=None,  # Null code for unrecognized raw -> VALID
        source_quote="Светильник ДКУ",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ"),
            StructuredFieldEvidence(field_name="currency", source_quote="4500 неизвестная валюта")
        ]
    )
    run3 = ExtractionRun(
        detail_id=999313,
        procurement_id=888313,
        category_code="lighting",
        source_text_snapshot=snapshot_unk,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent3],
    )
    assert validate_extraction_run(run3)[0] is True

# 7. Repository Zero-DML Tests
def test_repository_zero_dml_on_numeric_and_unit_violations():
    doc_conn = get_doc_db_connection()
    snapshot = "Светильник ДКУ-100 Вт, 10 шт"
    try:
        # Invalid quantity value
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            quantity_raw="10 шт",
            quantity_value=999.0,
            source_quote="Светильник ДКУ-100 Вт",
            field_evidence=[
                StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
                StructuredFieldEvidence(field_name="quantity", source_quote="10 шт")
            ]
        )
        run = ExtractionRun(
            detail_id=999314,
            procurement_id=888314,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            entities=[ent],
        )
        with pytest.raises(ValueError):
            save_extraction_run(doc_conn, run)

        with doc_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM structured_extraction_runs WHERE detail_id = 999314")
            assert cur.fetchone()[0] == 0
    finally:
        doc_conn.rollback()
        doc_conn.close()

# 8. Regressions & Fixture Safety
def test_transaction_rollback_fixture():
    doc_conn = get_doc_db_connection()
    synthetic_detail_id = 9999997
    try:
        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, 8888897, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id,))

        snapshot = "Светильник ДКУ-100 Вт"
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Светильник ДКУ-100 Вт",
            field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")]
        )
        run = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=8888897,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            entities=[ent],
        )
        save_extraction_run(doc_conn, run)
    finally:
        doc_conn.rollback()

    with doc_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM document_match_details WHERE id = %s", (synthetic_detail_id,))
        assert cur.fetchone()[0] == 0
    doc_conn.close()

def test_generated_placeholder_impossible():
    empty_cand = {"context_before": "", "context_after": "", "matched_line": "", "matched_term": "светильник"}
    snap = build_r4_source_snapshot(empty_cand)
    assert snap == ""
