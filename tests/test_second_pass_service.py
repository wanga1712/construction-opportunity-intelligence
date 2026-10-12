"""Unit tests for SecondPassService."""
import json
from unittest.mock import MagicMock, patch

from src.services.second_pass_service import (
    build_second_pass_prompt,
    compute_hash,
    extract_evidence_snippets,
    parse_second_pass_json,
    SECOND_PASS_MODEL,
    SECOND_PASS_PROMPT_VERSION,
)


def test_parse_second_pass_json_clean():
    """STRONG category relevance + evidence -> GOLD (assigned by code, not Qwen)."""
    raw_json = json.dumps({
        "raw_model_suggestion": {"medal": "GOLD"},
        "object_classification": {
            "object_family": "COMMERCIAL",
            "object_type": "Метрополитен",
            "object_subtype": "Вестибюль",
            "work_stage": "Строительство"
        },
        "category_evaluations": [
            {
                "category_code": "waterproofing",
                "relevance_level": "STRONG",
                "reason": "846 m2 наплавляемая гидроизоляция",
                "findings": ["наплавляемая гидроизоляция 846,3 м2"],
                "evidence_refs": [{"document_name": "Смета.pdf", "matched_term": "гидроизоляция"}],
                "positive_signals": ["гидроизоляция"],
                "negative_signals": [],
                "commercial_exclusions": []
            }
        ],
        "commercial_exclusions": [],
        "found_facts": [
            {
                "product_name_normalized": "Наплавляемая битумно-полимерная гидроизоляция",
                "category_code": "waterproofing",
                "quantity": 846.3,
                "unit": "м2",
                "unit_price": None,
                "total_price": None,
                "document_name": "Смета.pdf",
                "source_quote": "Наплавляемая битумно-полимерная гидроизоляция 846,3 м2"
            }
        ],
        "model_reason": "Подтвержденная гидроизоляция в смете",
        "model_name": "qwen2.5:7b",
        "prompt_version": SECOND_PASS_PROMPT_VERSION
    })
    parsed = parse_second_pass_json(raw_json)
    assert parsed["model_medal"] == "GOLD"
    assert parsed["model_state"] == "ASSESSED"
    assert parsed["model_score"] == 85
    assert parsed["semantics_version"] == 2
    assert parsed["price_used_for_medal"] is False
    assert parsed["raw_model_suggestion"]["authoritative"] is False
    assert parsed["prompt_version"] == SECOND_PASS_PROMPT_VERSION
    assert len(parsed["found_facts"]) == 1
    assert parsed["category_evaluations"][0]["relevance_level"] == "STRONG"
    assert parsed["category_evaluations"][0]["evidence_supported"] is True


def test_parse_second_pass_json_fallback():
    raw = "```json\n{\"model_medal\": \"invalid_medal\", \"model_score\": \"not_a_number\"}\n```"
    parsed = parse_second_pass_json(raw)
    assert parsed["model_medal"] == "WOOD"
    assert parsed["model_score"] == 10
    assert parsed["medal_support_type"] == "NEGATIVE/EXCLUSION"


def test_parse_second_pass_json_defensive_facts():
    """Empty fact rows are dropped; MODERATE relevance + evidence -> SILVER."""
    raw_json = json.dumps({
        "object_classification": {"object_family": "COMMERCIAL"},
        "category_evaluations": [
            {
                "category_code": "lighting",
                "relevance_level": "MODERATE",
                "evidence_refs": [{"document_name": "Doc.pdf", "matched_term": "Светильник ДПА"}],
            }
        ],
        "found_facts": [
            {"product_name_normalized": "", "document_name": "Doc.pdf"},
            {"product_name_normalized": "Светильник ДПА", "document_name": None, "source_quote": "Светильник ДПА 3 шт"}
        ]
    })
    parsed = parse_second_pass_json(raw_json)
    assert parsed["model_medal"] == "SILVER"
    assert len(parsed["found_facts"]) == 1
    assert parsed["found_facts"][0]["product_name_normalized"] == "Светильник ДПА"
    assert parsed["found_facts"][0]["document_name"] == "Документация"
    assert parsed["medal_support_type"] in ("FACT", "MIXED")


def test_build_second_pass_prompt():
    proc = {
        "id": 165114,
        "contract_number": "32515285171",
        "auction_name": "Строительство метро",
        "customer": "Моспроект",
        "initial_price": 773628642.43,
        "okpd_code": "41.20.40.100",
        "fz": "223-FZ"
    }
    stats = {"document_count": 20, "processed_document_count": 20, "evidence_count": 2452}
    snippets = [{
        "category_code": "waterproofing",
        "document_name": "Смета.pdf",
        "location": "1:31",
        "matched_term": "гидроизоляция",
        "text": "Наплавляемая битумно-полимерная гидроизоляция 846 м2"
    }]
    prompt = build_second_pass_prompt(proc, stats, snippets)
    assert "165114" in prompt
    assert "32515285171" in prompt
    assert "Строительство метро" in prompt
    assert "waterproofing" in prompt
    assert "Наплавляемая битумно-полимерная гидроизоляция" in prompt
