"""
Unit & Integration Tests for R4 Structured Fact Data Contract & Storage Model.
NO live LLM or Qwen model calls are made in these tests.
"""

import hashlib
import pytest
from typing import Dict, Any

from tender_documents_research.document_processor.structured_fact_contract import (
    ExtractionRun,
    StructuredEntity,
    StructuredAttribute,
    STRUCTURED_EXTRACTOR_NAME,
    STRUCTURED_EXTRACTOR_VERSION,
    EXTRACTION_METHOD,
    PROMPT_VERSION,
    ALLOWED_ENTITY_TYPES,
    verify_source_quote,
    normalize_whitespace,
    compute_sha256,
    compute_entity_fingerprint,
    compute_attribute_fingerprint,
    validate_extraction_run,
    extraction_run_to_dict,
    extraction_run_from_dict,
)
from tender_documents_research.document_processor.context_validator_service import get_doc_db_connection
from tender_documents_research.document_processor.structured_fact_repository import (
    save_extraction_run,
    get_extraction_run_by_detail,
)

def test_quote_verification_valid_quote():
    source_text = "Светильник светодиодный ДКУ-100Вт IP65, количество: 10 шт, цена: 4500 руб."
    
    # Exact quote
    assert verify_source_quote("ДКУ-100Вт IP65", source_text) is True
    # Quote with whitespace differences (newlines/tabs)
    assert verify_source_quote("ДКУ-100Вт\n IP65", source_text) is True
    assert verify_source_quote("  количество:   10 шт ", source_text) is True

def test_quote_verification_hallucinated_quote_rejection():
    source_text = "Светильник светодиодный ДКУ-100Вт IP65, количество: 10 шт."
    
    # Hallucinated manufacturer not in text
    assert verify_source_quote("Производитель ООО Вартон", source_text) is False
    # Empty or whitespace quote
    assert verify_source_quote("", source_text) is False
    assert verify_source_quote("   ", source_text) is False

def test_nullable_manufacturer_brand_model():
    snapshot = "Плита минераловатная ТЕХНОФАС 100 мм, 50 м3"
    quote = "Плита минераловатная ТЕХНОФАС 100 мм"

    # Manufacturer, brand, and model are allowed to be None (Section 10)
    entity = StructuredEntity(
        entity_type="MATERIAL",
        product_name_raw="Плита минераловатная ТЕХНОФАС 100 мм",
        product_name_normalized="ПЛИТА МИНЕРАЛОВАТНАЯ ТЕХНОФАС 100 ММ",
        manufacturer_raw=None,
        manufacturer_normalized=None,
        brand_raw=None,
        brand_normalized=None,
        model_article_raw=None,
        model_article_normalized=None,
        quantity_value=50.0,
        quantity_unit_raw="м3",
        quantity_unit_normalized="m3",
        source_quote=quote,
    )

    run = ExtractionRun(
        detail_id=999999,
        procurement_id=888888,
        category_code="thermal_insulation",
        source_text_snapshot=snapshot,
        entities=[entity],
    )

    is_valid, errors = validate_extraction_run(run)
    assert is_valid is True, f"Validation failed with errors: {errors}"
    assert entity.manufacturer_raw is None
    assert entity.brand_raw is None
    assert entity.model_article_raw is None

def test_raw_and_normalized_preservation():
    attr = StructuredAttribute(
        attribute_name="Мощность",
        attribute_name_normalized="power",
        raw_value="40 Вт",
        normalized_value="40 W",
        numeric_value=40.0,
        unit_raw="Вт",
        unit_normalized="W",
        source_quote="40 Вт",
    )

    assert attr.raw_value == "40 Вт"
    assert attr.normalized_value == "40 W"
    assert attr.numeric_value == 40.0
    assert attr.unit_raw == "Вт"
    assert attr.unit_normalized == "W"

def test_stable_fingerprints_and_idempotency():
    fp1 = compute_entity_fingerprint(
        "PRODUCT", "Светильник ДКУ", "Вартон", "Varton", "DKU-100", "Светильник ДКУ 100Вт"
    )
    fp2 = compute_entity_fingerprint(
        "PRODUCT", "Светильник ДКУ", "Вартон", "Varton", "DKU-100", "Светильник ДКУ 100Вт"
    )
    assert fp1 == fp2
    assert len(fp1) == 64

    afp1 = compute_attribute_fingerprint("power", "40 Вт", "40 Вт")
    afp2 = compute_attribute_fingerprint("power", "40 Вт", "40 Вт")
    assert afp1 == afp2
    assert len(afp1) == 64

def test_serialization_deserialization_roundtrip():
    snapshot = "Кабель ВВГнг-LS 3х2.5 мм2, 500 м"
    quote = "Кабель ВВГнг-LS 3х2.5 мм2"

    attr = StructuredAttribute(
        attribute_name="Сечение",
        attribute_name_normalized="cross_section",
        raw_value="3х2.5 мм2",
        normalized_value="3x2.5 mm2",
        numeric_value=2.5,
        unit_raw="мм2",
        unit_normalized="mm2",
        source_quote="3х2.5 мм2",
    )

    entity = StructuredEntity(
        entity_type="PRODUCT",
        product_name_raw="Кабель ВВГнг-LS 3х2.5 мм2",
        quantity_value=500.0,
        quantity_unit_raw="м",
        quantity_unit_normalized="m",
        source_quote=quote,
        attributes=[attr],
    )

    original_run = ExtractionRun(
        detail_id=999901,
        procurement_id=888801,
        category_code="cables",
        source_text_snapshot=snapshot,
        entities=[entity],
    )

    dict_data = extraction_run_to_dict(original_run)
    reconstructed_run = extraction_run_from_dict(dict_data)

    assert reconstructed_run.detail_id == original_run.detail_id
    assert reconstructed_run.source_text_sha256 == original_run.source_text_sha256
    assert len(reconstructed_run.entities) == 1
    assert reconstructed_run.entities[0].product_name_raw == "Кабель ВВГнг-LS 3х2.5 мм2"
    assert len(reconstructed_run.entities[0].attributes) == 1
    assert reconstructed_run.entities[0].attributes[0].numeric_value == 2.5

def test_synthetic_contract_persistence_and_retrieval():
    """
    Synthetic Contract Test (Section 22).
    Persists a multi-entity, multi-attribute synthetic run fixture in PostgreSQL DB,
    retrieves it, verifies all raw/normalized fields, attributes, SHA, and provenance,
    and then cleans up the synthetic test fixture.
    """
    doc_conn = get_doc_db_connection()

    # Create synthetic detail_id parent for FK constraint
    synthetic_detail_id = 9999999
    synthetic_procurement_id = 8888888
    
    with doc_conn.cursor() as cur:
        # Check if dummy match_detail parent exists or insert temporary fixture row
        cur.execute("SELECT id FROM document_match_details WHERE id = %s", (synthetic_detail_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO document_match_details (
                    id, procurement_id, category_code, validation_status,
                    validator_name, validator_version, validation_method, pipeline_generation
                ) VALUES (
                    %s, %s, 'lighting', 'CONFIRMED',
                    'context_validator', 'v4', 'QWEN_CONTEXT_V4', 'S13_V4_EXHAUSTIVE_CONTEXT'
                )
            """, (synthetic_detail_id, synthetic_procurement_id))
    doc_conn.commit()

    try:
        snapshot = (
            "Позиция 1: Светильник светодиодный ДКУ-100, Мощность 40 Вт, Световой поток 5000 лм. "
            "Позиция 2: Провод СИП-4 2х16 мм2, длина 1000 м."
        )

        attr1 = StructuredAttribute(
            attribute_name="Мощность",
            attribute_name_normalized="power",
            raw_value="40 Вт",
            normalized_value="40 W",
            numeric_value=40.0,
            unit_raw="Вт",
            unit_normalized="W",
            source_quote="Мощность 40 Вт",
        )
        attr2 = StructuredAttribute(
            attribute_name="Световой поток",
            attribute_name_normalized="luminous_flux",
            raw_value="5000 лм",
            normalized_value="5000 lm",
            numeric_value=5000.0,
            unit_raw="лм",
            unit_normalized="lm",
            source_quote="Световой поток 5000 лм",
        )

        # Entity 1: Product with null manufacturer/brand/model
        ent1 = StructuredEntity(
            entity_type="PRODUCT",
            product_name_raw="Светильник светодиодный ДКУ-100",
            product_name_normalized="СВЕТИЛЬНИК СВЕТОДИОДНЫЙ ДКУ-100",
            manufacturer_raw=None,
            brand_raw=None,
            model_article_raw=None,
            quantity_value=1.0,
            quantity_unit_raw="шт",
            quantity_unit_normalized="pcs",
            source_quote="Светильник светодиодный ДКУ-100",
            attributes=[attr1, attr2],
        )

        # Entity 2: Cable material on SAME detail_id (Multiple entities per detail!)
        ent2 = StructuredEntity(
            entity_type="MATERIAL",
            product_name_raw="Провод СИП-4 2х16 мм2",
            product_name_normalized="ПРОВОД СИП-4 2Х16 ММ2",
            manufacturer_raw=None,
            brand_raw=None,
            model_article_raw=None,
            quantity_value=1000.0,
            quantity_unit_raw="м",
            quantity_unit_normalized="m",
            source_quote="Провод СИП-4 2х16 мм2, длина 1000 м",
        )

        run = ExtractionRun(
            detail_id=synthetic_detail_id,
            procurement_id=synthetic_procurement_id,
            category_code="lighting",
            source_text_snapshot=snapshot,
            status="COMPLETE",
            entities=[ent1, ent2],
        )

        # Validate run structure
        is_valid, val_errors = validate_extraction_run(run)
        assert is_valid is True, f"Synthetic run validation failed: {val_errors}"

        # Persist to DB
        run_id = save_extraction_run(doc_conn, run)
        doc_conn.commit()
        assert run_id > 0

        # Idempotent re-persist test (Section 15: REPEATED_PERSIST_SAME_RESULT_DUPLICATES=0)
        re_run_id = save_extraction_run(doc_conn, run)
        doc_conn.commit()
        assert re_run_id == run_id

        # Retrieve and verify
        retrieved_run = get_extraction_run_by_detail(doc_conn, synthetic_detail_id, STRUCTURED_EXTRACTOR_VERSION)
        assert retrieved_run is not None
        assert retrieved_run.detail_id == synthetic_detail_id
        assert retrieved_run.source_text_sha256 == compute_sha256(snapshot)
        assert len(retrieved_run.entities) == 2

        # Entity 1 checks
        r_ent1 = retrieved_run.entities[0]
        assert r_ent1.product_name_raw == "Светильник светодиодный ДКУ-100"
        assert r_ent1.manufacturer_raw is None
        assert r_ent1.brand_raw is None
        assert len(r_ent1.attributes) == 2

        # Attributes check
        r_attr1 = r_ent1.attributes[0]
        assert r_attr1.attribute_name_normalized == "power"
        assert r_attr1.numeric_value == 40.0
        assert r_attr1.unit_normalized == "W"

        r_attr2 = r_ent1.attributes[1]
        assert r_attr2.attribute_name_normalized == "luminous_flux"
        assert r_attr2.numeric_value == 5000.0

        # Entity 2 checks
        r_ent2 = retrieved_run.entities[1]
        assert r_ent2.entity_type == "MATERIAL"
        assert r_ent2.product_name_raw == "Провод СИП-4 2х16 мм2"
        assert r_ent2.quantity_value == 1000.0

    finally:
        # Clean up synthetic test fixture completely
        with doc_conn.cursor() as cur:
            cur.execute("DELETE FROM structured_extraction_runs WHERE detail_id = %s", (synthetic_detail_id,))
            cur.execute("DELETE FROM document_match_details WHERE id = %s", (synthetic_detail_id,))
        doc_conn.commit()
        doc_conn.close()
