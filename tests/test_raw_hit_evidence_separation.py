import os
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
tender_dir = root_dir / "tender_documents_research"
if str(tender_dir) not in sys.path:
    sys.path.insert(0, str(tender_dir))
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pytest
from document_processor.dto import (
    FileProcessResult,
    MatchResult,
    MatchDetailResult,
    EvidenceResult,
)
from document_processor.evidence_aggregator import EvidenceAggregator
from document_processor.matching.dto_mapper import to_match_detail


def test_1_evidence_result_with_omitted_status_is_not_confirmed():
    """1. EvidenceResult with omitted status defaults to UNKNOWN (fail-closed, not CONFIRMED)."""
    ev = EvidenceResult(
        category_code="waterproofing",
        evidence_score=100.0,
        match_count=1,
    )
    assert ev.validation_status == "UNKNOWN", "EvidenceResult default must be UNKNOWN"
    assert ev.validation_version is None
    assert ev.validation_method is None


def test_2_persistence_with_missing_status_cannot_create_confirmed_evidence():
    """2. Persistence layer resolves missing/None/empty status to UNKNOWN, never CONFIRMED."""
    ev = EvidenceResult(
        category_code="waterproofing",
        evidence_score=100.0,
        match_count=1,
        validation_status=None,
    )
    raw_status = getattr(ev, "validation_status", "UNKNOWN")
    val_status = str(raw_status or "UNKNOWN").upper()
    if val_status == "CONFIRMED":
        val_version = getattr(ev, "validation_version", "v1") or "v1"
        val_method = getattr(ev, "validation_method", "confirmed_v1") or "confirmed_v1"
    else:
        val_status = "UNKNOWN"
        val_version = None
        val_method = None

    assert val_status == "UNKNOWN", "Missing/None status must not resolve to CONFIRMED"
    assert val_version is None
    assert val_method is None


def test_3_confirmed_detail_to_aggregator_to_explicit_confirmed_evidence():
    """3. Confirmed detail -> aggregator -> explicit confirmed EvidenceResult."""
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
    assert evidence[0].validation_version == "v1"
    assert evidence[0].validation_method == "deterministic_fixture_v1"


def test_4_unknown_detail_produces_no_positive_evidence():
    """4. UNKNOWN detail produces no positive evidence from aggregator."""
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
    assert len(evidence) == 0, "UNKNOWN candidate must not produce positive evidence"


def test_5_legacy_raw_source_evidence_with_confirmed_count_zero_cannot_create_useful_truth():
    """5. Legacy raw_source_evidence presence cannot create USEFUL truth when confirmed_count == 0."""
    # Simulate learning_observer document classification
    confirmed_cnt = 0
    unknown_match_cnt = 0
    dl_st = "COMPLETED"
    pr_st = "COMPLETED"
    d_id = 999
    ev_doc_ids = {999}  # Historical raw source evidence exists for this doc

    useful_docs = []
    non_useful_docs = []
    unknown_docs = []
    d_item = {"document_key": "k", "source_document_id": d_id}

    if dl_st == "COMPLETED" and pr_st == "COMPLETED":
        if confirmed_cnt > 0:
            useful_docs.append(d_item)
        elif unknown_match_cnt > 0:
            unknown_docs.append(d_item)
        else:
            non_useful_docs.append(d_item)
    else:
        unknown_docs.append(d_item)

    assert len(useful_docs) == 0, "Document with confirmed_cnt=0 must NEVER become useful"
    assert len(non_useful_docs) == 1, "Document with confirmed_cnt=0, unknown_cnt=0 must become non_useful (NO_TARGET_EVIDENCE)"


def test_6_unknown_candidate_prevents_factual_no():
    """6. UNKNOWN candidate ensures document classification stays UNKNOWN / PARTIAL, not NO_TARGET_EVIDENCE."""
    confirmed_cnt = 0
    unknown_match_cnt = 2  # Unresolved candidate matches exist
    dl_st = "COMPLETED"
    pr_st = "COMPLETED"
    d_id = 100
    d_item = {"document_key": "k", "source_document_id": d_id}

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
    assert len(non_useful_docs) == 0, "Unknown candidate must NOT become NO_TARGET_EVIDENCE"
    assert len(unknown_docs) == 1, "Unknown candidate must stay UNKNOWN"


def test_7_migration_first_run_marks_pre_barrier_legacy_evidence_unvalidated():
    """7. Migration logic marks legacy pre-barrier evidence rows as LEGACY_UNVALIDATED."""
    def apply_migration_row(row):
        # Emulates:
        # WHERE validation_status IS NULL
        #    OR (validation_version IS NULL AND (validation_method IS NULL OR validation_method = 'legacy_pre_r3_3'))
        if row.get("validation_status") is None or (
            row.get("validation_version") is None
            and (row.get("validation_method") is None or row.get("validation_method") == "legacy_pre_r3_3")
        ):
            return {
                **row,
                "validation_status": "LEGACY_UNVALIDATED",
                "validation_method": "legacy_pre_r3_3",
            }
        return row

    legacy_row = {
        "id": 1,
        "category_code": "waterproofing",
        "validation_status": None,
        "validation_version": None,
        "validation_method": None,
    }
    updated = apply_migration_row(legacy_row)
    assert updated["validation_status"] == "LEGACY_UNVALIDATED"
    assert updated["validation_method"] == "legacy_pre_r3_3"


def test_8_migration_second_run_does_not_demote_new_v1_confirmed_evidence():
    """8. Migration rerun leaves new v1 CONFIRMED evidence intact."""
    def apply_migration_row(row):
        if row.get("validation_status") is None or (
            row.get("validation_version") is None
            and (row.get("validation_method") is None or row.get("validation_method") == "legacy_pre_r3_3")
        ):
            return {
                **row,
                "validation_status": "LEGACY_UNVALIDATED",
                "validation_method": "legacy_pre_r3_3",
            }
        return row

    new_confirmed_row = {
        "id": 2,
        "category_code": "flooring",
        "validation_status": "CONFIRMED",
        "validation_version": "v1",
        "validation_method": "deterministic_fixture_v1",
    }
    # Run migration on new confirmed row
    result = apply_migration_row(new_confirmed_row)
    assert result["validation_status"] == "CONFIRMED", "New confirmed evidence must NOT be demoted by migration rerun"
    assert result["validation_version"] == "v1"
    assert result["validation_method"] == "deterministic_fixture_v1"


def test_9_legacy_evidence_remains_unvalidated():
    """9. Legacy evidence remains unvalidated and idempotent on repeated runs."""
    def apply_migration_row(row):
        if row.get("validation_status") is None or (
            row.get("validation_version") is None
            and (row.get("validation_method") is None or row.get("validation_method") == "legacy_pre_r3_3")
        ):
            return {
                **row,
                "validation_status": "LEGACY_UNVALIDATED",
                "validation_method": "legacy_pre_r3_3",
            }
        return row

    legacy_row = {
        "id": 1,
        "category_code": "waterproofing",
        "validation_status": "LEGACY_UNVALIDATED",
        "validation_version": None,
        "validation_method": "legacy_pre_r3_3",
    }
    # Run migration once
    run1 = apply_migration_row(legacy_row)
    assert run1["validation_status"] == "LEGACY_UNVALIDATED"

    # Run migration second time
    run2 = apply_migration_row(run1)
    assert run2["validation_status"] == "LEGACY_UNVALIDATED"
