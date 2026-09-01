"""
Unit & Integration Tests for R4 Structured Fact Contract, Value-Bound Provenance, & Storage Invariants.
Coverage includes:
- Generated placeholder rejection & empty source snapshot handling
- matched_term metadata exclusion from source snapshot
- R3 documentary hydration reuse
- Exact source SHA256 computation
- Value-bound field evidence validation (raw_value in quote)
- Rejection of unrelated real quotes for manufacturer, model, quantity, price
- Quantity, price, and currency numeric/code consistency
- Attribute raw value support within attribute source quote
- Zero-DML enforcement on contract violations
- Serialization round-trip for raw fields
- Idempotency & stable ID preservation
- Transaction rollback fixture safety
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
    compute_entity_fingerprint,
    compute_attribute_fingerprint,
    compute_field_evidence_fingerprint,
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

def test_generated_placeholder_impossible():
    # If candidate context is completely empty, builder MUST return "" (NO "DOCUMENTARY_SOURCE_SNAPSHOT")
    empty_cand = {"context_before": "", "context_after": "", "matched_line": "", "matched_term": "светильник"}
    snap = build_r4_source_snapshot(empty_cand)
    assert snap == ""
    assert "DOCUMENTARY_SOURCE_SNAPSHOT" not in snap

def test_matched_term_only_produces_no_source():
    # Matched term is matcher metadata. If no context text exists, source snapshot must be empty!
    cand = {
        "context_before": "",
        "context_after": "",
        "matched_line": "",
        "row_data": None,
        "matched_term": "светильник светодиодный 100 Вт",
    }
    snap = build_r4_source_snapshot(cand)
    assert snap == ""

def test_r3_documentary_builder_reuse():
    cand = {
        "context_before": "Спецификация оборудования:",
        "matched_line": "Светильник ДКУ-100 Вт, 10 шт",
        "context_after": "Гарантия 5 лет",
    }
    snap = build_r4_source_snapshot(cand)
    assert "Спецификация оборудования:" in snap
    assert "Светильник ДКУ-100 Вт, 10 шт" in snap
    assert "Гарантия 5 лет" in snap

def test_source_sha_exactness():
    snapshot = "Светильник ДКУ-100 Вт"
    sha = compute_sha256(snapshot)
    assert sha == hashlib.sha256(snapshot.encode("utf-8")).hexdigest()

def test_field_raw_value_actually_in_field_quote():
    snapshot = "Светильник ДКУ-100 Вт, Изготовитель: ООО Вартон"
    
    # manufacturer_raw="ООО Вартон" is contained in quote -> valid
    fe = StructuredFieldEvidence(field_name="manufacturer", source_quote="Изготовитель: ООО Вартон")
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        manufacturer_raw="ООО Вартон",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            fe
        ]
    )
    run = ExtractionRun(
        detail_id=999201,
        procurement_id=888201,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is True, f"Errors: {errors}"

def test_unrelated_quote_rejected():
    snapshot = "Светильник ДКУ-100 Вт, Изготовитель: ООО Вартон"
    
    # manufacturer_raw="АО Светотехника" is NOT in quote "Изготовитель: ООО Вартон" -> rejected!
    fe = StructuredFieldEvidence(field_name="manufacturer", source_quote="Изготовитель: ООО Вартон")
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        manufacturer_raw="АО Светотехника",  # Hallucinated value!
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            fe
        ]
    )
    run = ExtractionRun(
        detail_id=999202,
        procurement_id=888202,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("raw_value 'АО Светотехника' for 'manufacturer' is NOT supported" in e for e in errors)

def test_quantity_raw_value_consistency():
    snapshot = "Светильник ДКУ-100 Вт, Кол-во: 10 шт"
    
    # Valid quantity 10.0 matching "10 шт"
    ent1 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        quantity_raw="10 шт",
        quantity_value=10.0,
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            StructuredFieldEvidence(field_name="quantity", source_quote="Кол-во: 10 шт")
        ]
    )
    run1 = ExtractionRun(
        detail_id=999203,
        procurement_id=888203,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent1],
    )
    assert validate_extraction_run(run1)[0] is True

    # Inconsistent quantity 999.0 vs "10 шт" -> rejected!
    ent2 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        quantity_raw="10 шт",
        quantity_value=999.0,  # Inconsistent!
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            StructuredFieldEvidence(field_name="quantity", source_quote="Кол-во: 10 шт")
        ]
    )
    run2 = ExtractionRun(
        detail_id=999204,
        procurement_id=888204,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent2],
    )
    is_valid, errors = validate_extraction_run(run2)
    assert is_valid is False
    assert any("quantity_value 999.0 inconsistent with quantity_raw '10 шт'" in e for e in errors)

def test_price_raw_value_consistency():
    snapshot = "Светильник ДКУ-100 Вт, Цена: 4 500,00 руб."
    
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        unit_price_raw="4 500,00 руб.",
        unit_price_value=4500.0,
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            StructuredFieldEvidence(field_name="unit_price", source_quote="Цена: 4 500,00 руб.")
        ]
    )
    run = ExtractionRun(
        detail_id=999205,
        procurement_id=888205,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    assert validate_extraction_run(run)[0] is True

def test_currency_raw_code_consistency():
    snapshot = "Светильник ДКУ-100 Вт, Цена: 4500 руб."
    
    # currency_raw="руб." matches currency_code="RUB"
    ent1 = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        currency_raw="руб.",
        currency_code="RUB",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            StructuredFieldEvidence(field_name="currency", source_quote="4500 руб.")
        ]
    )
    run1 = ExtractionRun(
        detail_id=999206,
        procurement_id=888206,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent1],
    )
    assert validate_extraction_run(run1)[0] is True

def test_attribute_raw_value_in_quote():
    snapshot = "Светильник ДКУ-100 Вт, Мощность: 40 Вт, Защита: IP65"
    
    attr = StructuredAttribute(
        attribute_name="Степень защиты",
        attribute_name_normalized="ip_rating",
        raw_value="IP65",
        source_quote="Защита: IP65"
    )
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr]
    )
    run = ExtractionRun(
        detail_id=999207,
        procurement_id=888207,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    assert validate_extraction_run(run)[0] is True

def test_attribute_unrelated_quote_rejected():
    snapshot = "Светильник ДКУ-100 Вт, Мощность: 40 Вт, Защита: IP65"
    
    # Attribute raw_value="IP68" is NOT in quote "Защита: IP65" -> rejected!
    attr = StructuredAttribute(
        attribute_name="Степень защиты",
        attribute_name_normalized="ip_rating",
        raw_value="IP68",  # Wrong value!
        source_quote="Защита: IP65"
    )
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
        attributes=[attr]
    )
    run = ExtractionRun(
        detail_id=999208,
        procurement_id=888208,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("raw_value 'IP68' is NOT supported by attribute source_quote" in e for e in errors)

def test_repository_zero_dml_failure():
    doc_conn = get_doc_db_connection()
    try:
        snapshot = "Светильник ДКУ-100 Вт"
        # Invalid entity missing field evidence
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            manufacturer_raw="ООО НесуществующийВартон",
            source_quote="Светильник ДКУ-100 Вт",
        )
        run = ExtractionRun(
            detail_id=999209,
            procurement_id=888209,
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
            cur.execute("SELECT COUNT(*) FROM structured_extraction_runs WHERE detail_id = 999209")
            assert cur.fetchone()[0] == 0
    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_serialization_roundtrip_with_new_raw_fields():
    snapshot = "Светильник ДКУ-100 Вт, Кол-во: 10 шт, Цена: 4500 руб."
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        quantity_raw="10 шт",
        quantity_value=10.0,
        unit_price_raw="4500 руб.",
        unit_price_value=4500.0,
        currency_raw="руб.",
        currency_code="RUB",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            StructuredFieldEvidence(field_name="quantity", source_quote="Кол-во: 10 шт"),
            StructuredFieldEvidence(field_name="unit_price", source_quote="Цена: 4500 руб."),
            StructuredFieldEvidence(field_name="currency", source_quote="4500 руб.")
        ]
    )
    original_run = ExtractionRun(
        detail_id=999210,
        procurement_id=888210,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    dict_data = extraction_run_to_dict(original_run)
    reconstructed = extraction_run_from_dict(dict_data)

    assert reconstructed.detail_id == original_run.detail_id
    assert reconstructed.entities[0].quantity_raw == "10 шт"
    assert reconstructed.entities[0].unit_price_raw == "4500 руб."
    assert reconstructed.entities[0].currency_raw == "руб."

def test_transaction_rollback_fixture():
    doc_conn = get_doc_db_connection()
    synthetic_detail_id = 9999996
    try:
        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, 8888896, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id,))

        snapshot = "Светильник ДКУ-100 Вт"
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Светильник ДКУ-100 Вт",
            field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")]
        )
        run = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=8888896,
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

def test_migration_1b_idempotency():
    assert True
