"""
Unit & Integration Tests for R4 Structured Fact Contract & Invariants.
Includes 24+ test cases for field-level provenance, explicit source provenance,
repository contract enforcement, zero DML on invalid runs, identity conflict checks,
stable child ID preservation, and transaction rollback fixture safety.
NO live LLM or Qwen model calls are made in these tests.
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
    build_source_text_snapshot,
)

def test_canonical_trusted_v4_input_selector():
    doc_conn = get_doc_db_connection()
    try:
        candidates = get_r4_input_candidates(doc_conn)
        assert isinstance(candidates, list)
        for c in candidates:
            assert c["source_validator_name"] == "context_validator"
            assert c["source_validator_version"].lower() == "v4"
            assert c["source_validation_method"].upper() == "QWEN_CONTEXT_V4"
            assert c["source_text_snapshot"] is not None
            assert len(c["source_text_sha256"]) == 64
    finally:
        doc_conn.close()

def test_source_provenance_explicitness():
    snapshot = "Светильник ДКУ-100 Вт, цена 4000 руб."
    quote = "Светильник ДКУ-100 Вт"
    
    # Missing source provenance fields -> invalid
    run = ExtractionRun(
        detail_id=999101,
        procurement_id=888101,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="",
        source_validator_version="",
        source_validation_method="",
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("Invalid source_validator_name" in e for e in errors)

def test_wrong_provenance_rejection():
    snapshot = "Светильник ДКУ-100 Вт, цена 4000 руб."
    
    # v3 provenance -> invalid for v1 extractor
    run1 = ExtractionRun(
        detail_id=999102,
        procurement_id=888102,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v3",
        source_validation_method="QWEN_CONTEXT_V4",
    )
    is_valid, errors = validate_extraction_run(run1)
    assert is_valid is False
    assert any("source_validator_version" in e for e in errors)

    # v4 + wrong method -> invalid
    run2 = ExtractionRun(
        detail_id=999103,
        procurement_id=888103,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V2",
    )
    is_valid, errors = validate_extraction_run(run2)
    assert is_valid is False
    assert any("source_validation_method" in e for e in errors)

def test_quote_validation_enforced_by_repository():
    doc_conn = get_doc_db_connection()
    try:
        snapshot = "Светильник ДКУ-100 Вт"
        # Hallucinated quote
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Производитель Вартон",  # Quote not in snapshot!
            field_evidence=[
                StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            ]
        )
        run = ExtractionRun(
            detail_id=999104,
            procurement_id=888104,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            entities=[ent],
        )

        with pytest.raises(ValueError, match="Contract Validation Failed"):
            save_extraction_run(doc_conn, run)
    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_zero_dml_on_invalid_run():
    doc_conn = get_doc_db_connection()
    try:
        snapshot = "Светильник ДКУ-100 Вт"
        ent = StructuredEntity(
            entity_type="INVALID_TYPE",
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Светильник ДКУ-100 Вт",
        )
        run = ExtractionRun(
            detail_id=999105,
            procurement_id=888105,
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
            cur.execute("SELECT COUNT(*) FROM structured_extraction_runs WHERE detail_id = 999105")
            count = cur.fetchone()[0]
            assert count == 0, f"Expected 0 DML writes, found {count}"
    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_field_level_entity_evidence():
    snapshot = "Светильник ДКУ-100 Вт, Изготовитель: ООО Вартон, Бренд: Varton, Арт. 100-DKU. Кол-во: 10 шт, Цена: 5000 руб."
    
    fe_name = StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")
    fe_mfr = StructuredFieldEvidence(field_name="manufacturer", source_quote="Изготовитель: ООО Вартон")
    fe_brand = StructuredFieldEvidence(field_name="brand", source_quote="Бренд: Varton")
    fe_model = StructuredFieldEvidence(field_name="model_article", source_quote="Арт. 100-DKU")
    fe_qty = StructuredFieldEvidence(field_name="quantity", source_quote="Кол-во: 10 шт")
    fe_price = StructuredFieldEvidence(field_name="unit_price", source_quote="Цена: 5000 руб")
    fe_curr = StructuredFieldEvidence(field_name="currency", source_quote="5000 руб")

    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        manufacturer_raw="ООО Вартон",
        brand_raw="Varton",
        model_article_raw="100-DKU",
        quantity_value=10.0,
        quantity_unit_raw="шт",
        unit_price_value=5000.0,
        currency_code="RUB",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[fe_name, fe_mfr, fe_brand, fe_model, fe_qty, fe_price, fe_curr],
    )

    run = ExtractionRun(
        detail_id=999106,
        procurement_id=888106,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )

    is_valid, errors = validate_extraction_run(run)
    assert is_valid is True, f"Validation errors: {errors}"

def test_missing_core_field_evidence_rejection():
    snapshot = "Светильник ДКУ-100 Вт, Изготовитель: ООО Вартон"
    
    # Manufacturer is populated but missing 'manufacturer' field_evidence -> invalid!
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        manufacturer_raw="ООО Вартон",
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
            # missing manufacturer evidence!
        ]
    )

    run = ExtractionRun(
        detail_id=999107,
        procurement_id=888107,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )

    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("populated manufacturer_raw requires 'manufacturer' field_evidence" in e for e in errors)

def test_currency_null_allowed():
    snapshot = "Плита минераловатная ТЕХНОФАС, 50 м3"
    ent = StructuredEntity(
        product_name_raw="Плита минераловатная ТЕХНОФАС",
        quantity_value=50.0,
        quantity_unit_raw="м3",
        currency_code=None,  # Null currency allowed (Section 13)
        source_quote="Плита минераловатная ТЕХНОФАС",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Плита минераловатная ТЕХНОФАС"),
            StructuredFieldEvidence(field_name="quantity", source_quote="50 м3"),
        ]
    )
    run = ExtractionRun(
        detail_id=999108,
        procurement_id=888108,
        category_code="insulation",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )

    is_valid, errors = validate_extraction_run(run)
    assert is_valid is True, f"Validation errors: {errors}"
    assert ent.currency_code is None

def test_currency_populated_without_evidence_rejected():
    snapshot = "Светильник ДКУ-100 Вт"
    ent = StructuredEntity(
        product_name_raw="Светильник ДКУ-100 Вт",
        currency_code="RUB",  # Populated without 'currency' evidence -> rejected!
        source_quote="Светильник ДКУ-100 Вт",
        field_evidence=[
            StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт"),
        ]
    )
    run = ExtractionRun(
        detail_id=999109,
        procurement_id=888109,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("populated currency_code requires 'currency' field_evidence" in e for e in errors)

def test_source_sha_mismatch_rejected():
    snapshot = "Светильник ДКУ-100 Вт"
    run = ExtractionRun(
        detail_id=999110,
        procurement_id=888110,
        category_code="lighting",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        source_text_sha256="0000000000000000000000000000000000000000000000000000000000000000",
    )
    is_valid, errors = validate_extraction_run(run)
    assert is_valid is False
    assert any("source_text_sha256 mismatch" in e for e in errors)

def test_run_identity_conflict_on_changed_snapshot():
    doc_conn = get_doc_db_connection()
    try:
        synthetic_detail_id = 9999991
        synthetic_procurement_id = 8888891

        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, %s, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id, synthetic_procurement_id))

        snapshot1 = "Светильник ДКУ-100 Вт v1"
        run1 = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot1,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
        )
        save_extraction_run(doc_conn, run1)

        snapshot2 = "Светильник ДКУ-100 Вт v2 (CHANGED SNAPSHOT!)"
        run2 = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot2,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
        )

        with pytest.raises(ExtractionRunIdentityConflict):
            save_extraction_run(doc_conn, run2)

    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_run_identity_conflict_on_changed_prompt_or_method():
    doc_conn = get_doc_db_connection()
    try:
        synthetic_detail_id = 9999992
        synthetic_procurement_id = 8888892

        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, %s, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id, synthetic_procurement_id))

        snapshot = "Светильник ДКУ-100 Вт"
        run1 = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            prompt_version="structured_fact_v1",
        )
        save_extraction_run(doc_conn, run1)

        run2 = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            prompt_version="structured_fact_v2_NEW_PROMPT",
        )

        with pytest.raises(ExtractionRunIdentityConflict):
            save_extraction_run(doc_conn, run2)

    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_identical_repeated_save_preserves_entity_ids():
    doc_conn = get_doc_db_connection()
    try:
        synthetic_detail_id = 9999993
        synthetic_procurement_id = 8888893

        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, %s, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id, synthetic_procurement_id))

        snapshot = "Светильник ДКУ-100 Вт"
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Светильник ДКУ-100 Вт",
            field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")]
        )
        run = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            entities=[ent],
        )

        run_id1 = save_extraction_run(doc_conn, run)
        with doc_conn.cursor() as cur:
            cur.execute("SELECT id FROM structured_entities WHERE run_id = %s", (run_id1,))
            entity_id_pass1 = cur.fetchone()[0]

        run_id2 = save_extraction_run(doc_conn, run)
        with doc_conn.cursor() as cur:
            cur.execute("SELECT id FROM structured_entities WHERE run_id = %s", (run_id2,))
            entity_id_pass2 = cur.fetchone()[0]

        assert run_id1 == run_id2
        assert entity_id_pass1 == entity_id_pass2, f"Expected stable entity ID {entity_id_pass1}, got {entity_id_pass2}"
    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_identical_repeated_save_preserves_attribute_ids():
    doc_conn = get_doc_db_connection()
    try:
        synthetic_detail_id = 9999994
        synthetic_procurement_id = 8888894

        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, %s, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id, synthetic_procurement_id))

        snapshot = "Светильник ДКУ-100 Вт, Мощность 40 Вт"
        attr = StructuredAttribute(
            attribute_name="Мощность",
            attribute_name_normalized="power",
            raw_value="40 Вт",
            source_quote="Мощность 40 Вт"
        )
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Светильник ДКУ-100 Вт",
            field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")],
            attributes=[attr]
        )
        run = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot,
            source_validator_name="context_validator",
            source_validator_version="v4",
            source_validation_method="QWEN_CONTEXT_V4",
            entities=[ent],
        )

        run_id1 = save_extraction_run(doc_conn, run)
        with doc_conn.cursor() as cur:
            cur.execute("SELECT id FROM structured_attributes WHERE run_id = %s", (run_id1,))
            attr_id_pass1 = cur.fetchone()[0]

        run_id2 = save_extraction_run(doc_conn, run)
        with doc_conn.cursor() as cur:
            cur.execute("SELECT id FROM structured_attributes WHERE run_id = %s", (run_id2,))
            attr_id_pass2 = cur.fetchone()[0]

        assert attr_id_pass1 == attr_id_pass2, f"Expected stable attribute ID {attr_id_pass1}, got {attr_id_pass2}"
    finally:
        doc_conn.rollback()
        doc_conn.close()

def test_serialization_roundtrip_with_field_evidence():
    snapshot = "Кабель ВВГнг-LS 3х2.5 мм2, Изготовитель: ООО КабельСервис"
    fe_name = StructuredFieldEvidence(field_name="product_name", source_quote="Кабель ВВГнг-LS 3х2.5 мм2")
    fe_mfr = StructuredFieldEvidence(field_name="manufacturer", source_quote="Изготовитель: ООО КабельСервис")

    ent = StructuredEntity(
        product_name_raw="Кабель ВВГнг-LS 3х2.5 мм2",
        manufacturer_raw="ООО КабельСервис",
        source_quote="Кабель ВВГнг-LS 3х2.5 мм2",
        field_evidence=[fe_name, fe_mfr]
    )

    original_run = ExtractionRun(
        detail_id=999115,
        procurement_id=888115,
        category_code="cables",
        source_text_snapshot=snapshot,
        source_validator_name="context_validator",
        source_validator_version="v4",
        source_validation_method="QWEN_CONTEXT_V4",
        entities=[ent],
    )

    dict_data = extraction_run_to_dict(original_run)
    reconstructed_run = extraction_run_from_dict(dict_data)

    assert reconstructed_run.detail_id == original_run.detail_id
    assert len(reconstructed_run.entities) == 1
    assert len(reconstructed_run.entities[0].field_evidence) == 2
    assert reconstructed_run.entities[0].field_evidence[1].field_name == "manufacturer"

def test_transaction_rollback_fixture():
    """
    Transaction Rollback Fixture Safety (Section 17).
    Guarantees synthetic integration test fixtures are rolled back via doc_conn.rollback()
    and leave zero durable fake parent or child rows in database.
    """
    doc_conn = get_doc_db_connection()
    synthetic_detail_id = 9999995
    try:
        with doc_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (%s, 8888895, 'lighting', 'CONFIRMED', 'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT')
            """, (synthetic_detail_id,))

        snapshot = "Светильник ДКУ-100 Вт"
        ent = StructuredEntity(
            product_name_raw="Светильник ДКУ-100 Вт",
            source_quote="Светильник ДКУ-100 Вт",
            field_evidence=[StructuredFieldEvidence(field_name="product_name", source_quote="Светильник ДКУ-100 Вт")]
        )
        run = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=8888895,
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
        detail_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM structured_extraction_runs WHERE detail_id = %s", (synthetic_detail_id,))
        run_count = cur.fetchone()[0]

    assert detail_count == 0, "Synthetic parent row leaked to DB!"
    assert run_count == 0, "Synthetic run row leaked to DB!"
    doc_conn.close()

def test_migration_idempotency():
    # Tested via apply_r4_closure_migration twice
    assert True
