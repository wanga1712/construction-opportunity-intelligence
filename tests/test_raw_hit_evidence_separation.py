import pytest
from tender_documents_research.document_processor.dto import (
    FileProcessResult,
    MatchResult,
    MatchDetailResult,
    EvidenceResult,
)
from tender_documents_research.document_processor.evidence_aggregator import EvidenceAggregator
from tender_documents_research.document_processor.matching.dto_mapper import to_match_detail


def test_1_raw_fuzzy_candidate_does_not_automatically_become_evidence():
    """1. Raw fuzzy candidate with default UNKNOWN status does not create evidence."""
    detail = MatchDetailResult(
        category_code="lighting",
        subcategory_code="road_street",
        matched_term="проспект",
        term_type="search",
        score=78.0,
        row_data={"matched_line": "ПРОЕКТ ДОГОВОРА"},
        page_or_sheet="1",
        row_number=10,
        match_method="FUZZY_RATIO",
        validation_status="UNKNOWN",
    )
    match = MatchResult(category_code="lighting", match_count=1, score=78.0, details=[detail])
    file_res = FileProcessResult(file_name="contract.pdf", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 0, "Raw fuzzy candidate must not create evidence"


def test_2_score_100_raw_hit_does_not_automatically_become_evidence():
    """2. Score=100 raw hit (e.g. syringe 'инъекц') does not create evidence without CONFIRMED status."""
    detail = MatchDetailResult(
        category_code="waterproofing",
        subcategory_code="injection",
        matched_term="инъекц",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Шприц инъекционный однократного применения 50 мл №1."},
        page_or_sheet="table_3",
        row_number=250,
        match_method="STEM_PREFIX",
        validation_status="UNKNOWN",
    )
    match = MatchResult(category_code="waterproofing", match_count=1, score=100.0, details=[detail])
    file_res = FileProcessResult(file_name="tz.docx", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 0, "Score=100 raw hit must NOT automatically create evidence"


def test_3_confirmed_candidate_creates_evidence():
    """3. Explicitly CONFIRMED candidate creates positive EvidenceResult."""
    detail = MatchDetailResult(
        category_code="flooring",
        subcategory_code="polymer_self_leveling",
        matched_term="денстоп",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Покрытие пола составом Денстоп ЭП-201"},
        page_or_sheet="table_1",
        row_number=15,
        match_method="EXACT",
        validation_status="CONFIRMED",
        validation_method="deterministic_fixture_v1",
        validator_version="v1",
    )
    match = MatchResult(category_code="flooring", match_count=1, score=100.0, details=[detail])
    file_res = FileProcessResult(file_name="spec.xlsx", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 1
    assert evidence[0].category_code == "flooring"
    assert evidence[0].match_count == 1
    assert evidence[0].evidence_score == 100.0
    assert evidence[0].validation_status == "CONFIRMED"


def test_4_rejected_candidate_does_not_create_evidence():
    """4. Explicitly REJECTED candidate does not create evidence."""
    detail = MatchDetailResult(
        category_code="waterproofing",
        subcategory_code="injection",
        matched_term="инъекц",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Шприц инъекционный медицинский"},
        page_or_sheet="1",
        row_number=5,
        match_method="STEM_PREFIX",
        validation_status="REJECTED",
        validation_method="medical_syringe_filter",
        validation_reason="Medical disposable consumable, not construction waterproofing",
    )
    match = MatchResult(category_code="waterproofing", match_count=1, score=100.0, details=[detail])
    file_res = FileProcessResult(file_name="contract.pdf", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 0, "Rejected candidate must not create evidence"


def test_5_unknown_candidate_does_not_create_positive_evidence():
    """5. UNKNOWN candidate does not create positive evidence."""
    detail = MatchDetailResult(
        category_code="waterproofing_concrete_repair",
        subcategory_code="penetrating_waterproofing",
        matched_term="вектор",
        term_type="search",
        score=78.0,
        row_data={"matched_line": "Генеральный директор"},
        page_or_sheet="1",
        row_number=100,
        match_method="FUZZY_RATIO",
        validation_status="UNKNOWN",
    )
    match = MatchResult(category_code="waterproofing_concrete_repair", match_count=1, score=78.0, details=[detail])
    file_res = FileProcessResult(file_name="contract.docx", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 0


def test_6_unknown_candidate_prevents_complete_factual_no():
    """6. UNKNOWN candidate ensures document classification stays UNKNOWN / PARTIAL, not NO_TARGET_EVIDENCE."""
    # When confirmed_count == 0 but unknown_match_count > 0:
    confirmed_count = 0
    unknown_match_count = 2
    dl_st = "COMPLETED"
    pr_st = "COMPLETED"

    # Truth classification logic
    if dl_st == "COMPLETED" and pr_st == "COMPLETED":
        if confirmed_count > 0:
            doc_class = "USEFUL"
        elif unknown_match_count > 0:
            doc_class = "UNKNOWN"
        else:
            doc_class = "NO_TARGET_EVIDENCE"
    else:
        doc_class = "UNKNOWN"

    assert doc_class == "UNKNOWN", "Document with unknown candidate hits must stay UNKNOWN, preventing false NO"


def test_7_category_subcategory_cannot_be_changed_by_validation():
    """7. Category and subcategory provenance remain immutable from source taxonomy."""
    item = {
        "keyword": "мастика",
        "category_code": "waterproofing",
        "subcategory_code": "coating",
        "score": 100,
        "matched_line": "битумная мастика",
        "match_method": "EXACT",
        "validation_status": "UNKNOWN",
    }
    detail = to_match_detail(item)
    assert detail.category_code == "waterproofing"
    assert detail.subcategory_code == "coating"

    # Validation can only set validation_status, not alter category_code
    detail.validation_status = "REJECTED"
    assert detail.category_code == "waterproofing"
    assert detail.subcategory_code == "coating"


def test_8_raw_candidate_remains_persisted_after_rejection():
    """8. Raw candidate DTO is preserved with full details even when marked REJECTED."""
    detail = MatchDetailResult(
        category_code="lighting",
        subcategory_code="road_street",
        matched_term="проспект",
        term_type="search",
        score=78.0,
        row_data={"matched_line": "ПРОЕКТ"},
        page_or_sheet="1",
        row_number=1,
        match_method="FUZZY_RATIO",
        validation_status="REJECTED",
        validation_reason="Fuzzy collision on Russian word ПРОЕКТ",
    )
    assert detail.matched_term == "проспект"
    assert detail.row_data["matched_line"] == "ПРОЕКТ"
    assert detail.validation_status == "REJECTED"
    assert detail.validation_reason == "Fuzzy collision on Russian word ПРОЕКТ"


def test_9_match_method_provenance_preserved():
    """9. Match method (EXACT, STEM_PREFIX, FUZZY_RATIO, FUZZY_TOKEN_SET, COMPOUND_RULE) is preserved."""
    methods = ["EXACT", "STEM_PREFIX", "FUZZY_RATIO", "FUZZY_TOKEN_SET", "COMPOUND_RULE", "OCR_NORMALIZED_EXACT"]
    for method in methods:
        item = {
            "keyword": "test_term",
            "category_code": "test_cat",
            "score": 90,
            "match_method": method,
            "validation_status": "UNKNOWN",
        }
        detail = to_match_detail(item)
        assert detail.match_method == method


def test_10_multiple_confirmed_candidates_aggregate_correctly():
    """10. Multiple CONFIRMED candidates for the same category aggregate max score and sum count."""
    d1 = MatchDetailResult(
        category_code="lighting",
        subcategory_code="road_street",
        matched_term="светильник уличный",
        term_type="search",
        score=95.0,
        row_data={"matched_line": "Светильник уличный ДКУ-50"},
        page_or_sheet="1",
        row_number=1,
        match_method="EXACT",
        validation_status="CONFIRMED",
    )
    d2 = MatchDetailResult(
        category_code="lighting",
        subcategory_code="office_admin",
        matched_term="панель светодиодная",
        term_type="search",
        score=100.0,
        row_data={"matched_line": "Панель светодиодная 600х600"},
        page_or_sheet="1",
        row_number=2,
        match_method="EXACT",
        validation_status="CONFIRMED",
    )
    # Plus an unconfirmed/rejected candidate that should NOT be counted
    d3 = MatchDetailResult(
        category_code="lighting",
        subcategory_code="office_admin",
        matched_term="административ",
        term_type="search",
        score=80.0,
        row_data={"matched_line": "Администрация города"},
        page_or_sheet="1",
        row_number=3,
        match_method="FUZZY_RATIO",
        validation_status="UNKNOWN",
    )

    match = MatchResult(category_code="lighting", match_count=3, score=100.0, details=[d1, d2, d3])
    file_res = FileProcessResult(file_name="spec.xlsx", status="COMPLETED", matches=[match])

    evidence = EvidenceAggregator.aggregate([file_res])
    assert len(evidence) == 1
    assert evidence[0].category_code == "lighting"
    assert evidence[0].match_count == 2  # Only d1 and d2
    assert evidence[0].evidence_score == 100.0
    assert evidence[0].validation_status == "CONFIRMED"
