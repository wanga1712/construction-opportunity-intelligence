"""Focused unit tests: DOCUMENT-CONFIRMED-OPPORTUNITY-FOUNDATION-1 (no DB)."""
from __future__ import annotations

from decimal import Decimal

from src.services.opportunity_confirmation_foundation import (
    AUTH_CONFIRMED,
    AUTH_PRELIMINARY,
    BASIS_DIRECT_SINGLE,
    BASIS_DOC_ENTITY_SUM,
    BASIS_DOC_EXPLICIT_TOTAL,
    BASIS_DOC_QTY_X_UNIT,
    BASIS_UNKNOWN,
    STATE_CANDIDATE,
    STATE_CONFIRMED,
    STATE_INSUFFICIENT,
    STATE_REJECTED,
    SUBCAT_CONFIRMED,
    SUBCAT_MODEL_CANDIDATE,
    category_state,
    commercial_scale_authority,
    current_effective_authority,
    derive_category_value_from_entities,
    evidence_fingerprint,
    should_apply_evidence,
    subcategory_state,
    works_value_gate,
)


def test_works_gate_blocks_contract_total():
    # WORKS may not use contract total / direct fallback
    assert works_value_gate("CONSTRUCTION_WORKS", BASIS_UNKNOWN) is False
    assert works_value_gate("DESIGN_AND_BUILD", BASIS_DIRECT_SINGLE) is False
    # WORKS may use document-derived category values
    assert works_value_gate("CONSTRUCTION_WORKS", BASIS_DOC_EXPLICIT_TOTAL) is True
    assert works_value_gate("CONSTRUCTION_WORKS", BASIS_DOC_ENTITY_SUM) is True
    # DIRECT_GOODS single-category fallback allowed
    assert works_value_gate("DIRECT_GOODS", BASIS_DIRECT_SINGLE) is True


def test_case_a_works_440m_no_docs_unknown_scale():
    scale, src = commercial_scale_authority(
        procurement_form="CONSTRUCTION_WORKS", opportunity_track="EMBEDDED_MATERIAL",
        basis=BASIS_UNKNOWN, category_value=None,
    )
    assert scale is None and src == "NOT_AVAILABLE"


def test_case_b_works_440m_docs_7_8m_scale_is_category_value():
    value = Decimal("7800000")
    scale, src = commercial_scale_authority(
        procurement_form="CONSTRUCTION_WORKS", opportunity_track="EMBEDDED_MATERIAL",
        basis=BASIS_DOC_EXPLICIT_TOTAL, category_value=value,
    )
    assert scale == value and src == "CONFIRMED_CATEGORY_DOCUMENT_VALUE"


def test_case_c_direct_missing_source_amount_uses_doc_total():
    value, basis = derive_category_value_from_entities(
        [{"structured_entity_id": 1, "total_price_value": "6 200 000,00"}]
    )
    assert value == Decimal("6200000.00")
    assert basis == BASIS_DOC_EXPLICIT_TOTAL


def test_decimal_safe_and_dedup_no_double_count():
    entities = [
        {"structured_entity_id": 1, "total_price_value": "6200000.00"},
        {"structured_entity_id": 1, "total_price_value": "6200000.00"},  # dup evidence row
        {"structured_entity_id": 2, "total_price_value": "1000000.00"},
    ]
    value, basis = derive_category_value_from_entities(entities)
    assert value == Decimal("7200000.00")   # dedup by entity id
    assert basis == BASIS_DOC_ENTITY_SUM


def test_qty_x_unit_requires_subject_bound():
    unbound, _ = derive_category_value_from_entities(
        [{"structured_entity_id": 1, "quantity_value": 500, "unit_price_value": 12400}]
    )
    assert unbound is None
    bound, basis = derive_category_value_from_entities(
        [{"structured_entity_id": 1, "quantity_value": 500, "unit_price_value": 12400, "subject_bound": True}]
    )
    assert bound == Decimal("6200000")
    assert basis == BASIS_DOC_QTY_X_UNIT


def test_category_state_object_candidate_without_evidence():
    assert category_state(procurement_form="CONSTRUCTION_WORKS", has_trusted_evidence=False,
                          confirmed_base_medal=None) == STATE_CANDIDATE
    assert category_state(procurement_form="CONSTRUCTION_WORKS", has_trusted_evidence=True,
                          confirmed_base_medal="GOLD") == STATE_CONFIRMED
    assert category_state(procurement_form="CONSTRUCTION_WORKS", has_trusted_evidence=False,
                          confirmed_base_medal=None, documents_terminal=True) == STATE_INSUFFICIENT
    assert category_state(procurement_form="CONSTRUCTION_WORKS", has_trusted_evidence=False,
                          confirmed_base_medal=None, has_safe_negative=True,
                          documents_terminal=True) == STATE_REJECTED


def test_subcategory_model_candidate_without_evidence():
    assert subcategory_state(procurement_form="CONSTRUCTION_WORKS",
                             has_subcategory_evidence=False) == SUBCAT_MODEL_CANDIDATE
    assert subcategory_state(procurement_form="CONSTRUCTION_WORKS",
                             has_subcategory_evidence=True) == SUBCAT_CONFIRMED


def test_current_effective_authority_preliminary_without_confirmed_base():
    assert current_effective_authority(None) == AUTH_PRELIMINARY
    assert current_effective_authority("GOLD") == AUTH_CONFIRMED


def test_evidence_idempotence_and_revision():
    fp = evidence_fingerprint(procurement_id=1061, category_code="waterproofing",
                              subcategory_code="polymer_coatings", entity_ids=[10, 11],
                              values=["7800000.00"], extractor_version="v1")
    assert should_apply_evidence(None, fp) is True
    assert should_apply_evidence(fp, fp) is False           # same snapshot -> no write
    fp2 = evidence_fingerprint(procurement_id=1061, category_code="waterproofing",
                               subcategory_code="polymer_coatings", entity_ids=[10, 11, 12],
                               values=["9000000.00"], extractor_version="v1")
    assert should_apply_evidence(fp, fp2) is True           # new evidence -> may revise


def test_multi_category_isolation_fingerprint():
    a = evidence_fingerprint(procurement_id=1, category_code="lighting", subcategory_code=None,
                             entity_ids=[1], values=["3000000"])
    b = evidence_fingerprint(procurement_id=1, category_code="waterproofing", subcategory_code=None,
                             entity_ids=[1], values=["3000000"])
    assert a != b
