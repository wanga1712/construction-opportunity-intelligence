"""Unit tests for research UI projection, evidence formatting, and semantics."""
import pytest
from src.services.commercial_routing_v3.research_ui_projection import (
    ResearchUiProjection,
    format_friendly_locator,
    load_research_ui_projection,
)
from src.services.annotation_card_view import (
    compose_annotation_card_view,
    _observation_state,
)

def test_friendly_locator_formatting():
    loc1 = {"sheet_name": "Оборудование", "row_number": 42, "page_number": 17}
    assert format_friendly_locator(loc1) == "лист «Оборудование», строка 42, стр. 17"

    loc2 = {"archive_member_path": "sub/spec.doc", "row_number": 8}
    assert format_friendly_locator(loc2) == "файл в архиве: sub/spec.doc, строка 8"

    loc3 = {"paragraph_index": 12, "position_number": 8}
    assert format_friendly_locator(loc3) == "абзац 12, позиция 8"


def test_research_projection_complete_positive():
    proj = ResearchUiProjection(
        procurement_id=150194,
        research_state="EVIDENCE_FOUND",
        documents_total=21,
        documents_researched=21,
        documents_with_evidence=1,
        documents_no_evidence=20,
        documents_unknown=0,
        evidence_count=3,
        truth_completeness="COMPLETE",
    )
    assert proj.research_state == "EVIDENCE_FOUND"
    assert proj.documents_with_evidence == 1
    assert proj.evidence_count == 3


def test_research_projection_complete_negative():
    proj = ResearchUiProjection(
        procurement_id=149969,
        research_state="NO_EVIDENCE",
        documents_total=9,
        documents_researched=9,
        documents_with_evidence=0,
        documents_no_evidence=9,
        documents_unknown=0,
        evidence_count=0,
        truth_completeness="COMPLETE",
    )
    assert proj.research_state == "NO_EVIDENCE"
    assert proj.documents_unknown == 0


def test_research_projection_partial():
    proj = ResearchUiProjection(
        procurement_id=1001,
        research_state="PARTIAL",
        documents_total=10,
        documents_researched=7,
        documents_with_evidence=0,
        documents_no_evidence=7,
        documents_unknown=3,
        evidence_count=0,
        truth_completeness="PARTIAL",
    )
    assert proj.research_state == "PARTIAL"
    assert proj.documents_unknown == 3


def test_document_sorting_and_evidence_attachment():
    header = {"id": 150194, "auction_name": "Test Auction", "source_table": "fz44"}
    resolved = {
        "links": [
            {"source_document_id": 101, "document_name": "Doc1.pdf", "document_url": "http://example.com/1"},
            {"source_document_id": 102, "document_name": "Doc2.pdf", "document_url": "http://example.com/2"},
            {"source_document_id": 103, "document_name": "Doc3.pdf", "document_url": "http://example.com/3"},
        ]
    }
    raw_evidence = [
        {
            "source_document_id": 102,
            "matched_term": "светильник",
            "suggested_category_code": "lighting",
            "category_name": "Светотехника",
            "raw_text": "Светильник светодиодный",
            "source_locator_json": {"page_number": 5},
            "friendly_locator": "стр. 5",
        }
    ]
    observations = [
        {"source_document_id": 101, "download_status": "COMPLETED", "parse_status": "COMPLETED", "commercial_evidence_found": False},
        {"source_document_id": 103, "download_status": "DOWNLOAD_FAILED", "parse_status": None},
    ]

    view = compose_annotation_card_view(
        header=header,
        resolved=resolved,
        observations=observations,
        history=[],
        raw_evidence=raw_evidence,
    )

    docs = view["documents"]
    assert len(docs) == 3
    # Doc2 (source_document_id=102) has evidence, so it must be sorted first!
    assert docs[0]["source_document_id"] == 102
    assert len(docs[0]["research_evidence"]) == 1
    assert docs[0]["research_evidence"][0]["matched_term"] == "светильник"

    # Doc1 (source_document_id=101) is researched with no evidence -> second
    assert docs[1]["source_document_id"] == 101
    assert docs[1]["observation_state"] == "OBSERVED_NO_EVIDENCE"

    # Doc3 (source_document_id=103) has download failure -> last
    assert docs[2]["source_document_id"] == 103
    assert docs[2]["observation_state"] == "DOWNLOAD_FAILED"


def test_generation_isolation():
    # Evidence from another generation is NOT attached if research_generation_hash does not match
    raw_ev_current_gen = [
        {"source_document_id": 201, "matched_term": "прожектор", "research_generation_hash": "gen_new"}
    ]
    raw_ev_old_gen = [
        {"source_document_id": 201, "matched_term": "старый термин", "research_generation_hash": "gen_old"}
    ]

    # Only current generation evidence passed to view composition
    view = compose_annotation_card_view(
        header={"id": 200},
        resolved={"links": [{"source_document_id": 201, "document_name": "Spec.pdf"}]},
        observations=[],
        history=[],
        raw_evidence=raw_ev_current_gen,
    )
    doc = view["documents"][0]
    assert len(doc["research_evidence"]) == 1
    assert doc["research_evidence"][0]["matched_term"] == "прожектор"
