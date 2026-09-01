"""Regression tests for context hydration fix (R3-4C).

Tests that hydrate_candidate_context() correctly resolves matched_line,
context_before, and context_after from row_data when DB columns are empty.

NO model calls. NO prompt changes. NO threshold changes.
"""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tender_documents_research.document_processor.context_validator import (
    hydrate_candidate_context,
    _is_empty_context,
    _format_raw_cells,
    _candidate_matched_line,
    ContextValidator,
    SYSTEM_PROMPT,
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_THRESHOLD,
)


# ============================================================
# Fixtures
# ============================================================

def _make_candidate(
    *,
    matched_line="",
    context_before=None,
    context_after=None,
    row_data=None,
    detail_id=99999,
    procurement_id=997,
    matched_term="test",
    category_code="lighting",
    subcategory_code="road_street",
    match_method="UNKNOWN",
    **kwargs,
):
    """Create a candidate dict with optional overrides."""
    c = {
        "detail_id": detail_id,
        "procurement_id": procurement_id,
        "matched_term": matched_term,
        "matched_line": matched_line,
        "context_before": context_before if context_before is not None else {},
        "context_after": context_after if context_after is not None else {},
        "row_data": row_data,
        "category_code": category_code,
        "category_name": "Освещение",
        "subcategory_code": subcategory_code,
        "subcategory_name": "Уличное освещение",
        "match_method": match_method,
        "document_name": "test.pdf",
        "procurement_okpd_code": "27.40.39.000",
        "procurement_okpd_name": "Светильники",
        "procurement_title": "Поставка светильников",
    }
    c.update(kwargs)
    return c


PRODUCTION_ROW_DATA = {
    "values": {"position": "Светильник с люминесцентными лампами до 4"},
    "headers": {"position": "Переключатель 3-х позиционный, 25А"},
    "raw_cells": [
        {"col": "A", "text": "3", "header": "9"},
        {"col": "B", "text": "Светильник с люминесцентными лампами до 4",
         "header": "Переключатель 3-х позиционный, 25А"},
        {"col": "C", "text": "шт", "header": "шт"},
        {"col": "D", "text": "49", "header": "2"},
    ],
    "context_before": [
        "2 | Электрический щит | шт | 5",
        "3 | Светильник с лампами накаливания | шт | 36",
    ],
    "context_after": [
        "4 | Счетчик , трехфазный, | шт | 1",
    ],
    "context_lines": 7,
    "header_line_number": 4658,
    "column_map": {"position": 1},
}


# ============================================================
# Test 1: Explicit matched_line wins over row_data
# ============================================================
def test_explicit_matched_line_wins():
    c = _make_candidate(
        matched_line="EXPLICIT MATCHED TEXT",
        row_data=PRODUCTION_ROW_DATA,
    )
    hydrated = hydrate_candidate_context(c)
    assert hydrated["matched_line"] == "EXPLICIT MATCHED TEXT"


# ============================================================
# Test 2: Empty explicit matched_line falls back to row_data
# ============================================================
def test_empty_matched_line_falls_back_to_row_data():
    c = _make_candidate(matched_line="", row_data=PRODUCTION_ROW_DATA)
    hydrated = hydrate_candidate_context(c)
    assert "Светильник" in hydrated["matched_line"]
    assert hydrated["matched_line"]  # non-empty


# ============================================================
# Test 3: Explicit context_before wins when non-empty
# ============================================================
def test_explicit_context_before_wins():
    c = _make_candidate(
        context_before=["EXPLICIT BEFORE LINE"],
        row_data=PRODUCTION_ROW_DATA,
    )
    hydrated = hydrate_candidate_context(c)
    assert hydrated["context_before"] == ["EXPLICIT BEFORE LINE"]


# ============================================================
# Test 4: {} explicit context_before falls back to row_data
# ============================================================
def test_empty_dict_context_before_falls_back():
    c = _make_candidate(context_before={}, row_data=PRODUCTION_ROW_DATA)
    hydrated = hydrate_candidate_context(c)
    assert isinstance(hydrated["context_before"], list)
    assert len(hydrated["context_before"]) > 0
    assert "Электрический щит" in hydrated["context_before"][0]


# ============================================================
# Test 5: [] explicit context_after falls back to row_data
# ============================================================
def test_empty_list_context_after_falls_back():
    c = _make_candidate(context_after=[], row_data=PRODUCTION_ROW_DATA)
    hydrated = hydrate_candidate_context(c)
    assert isinstance(hydrated["context_after"], list)
    assert len(hydrated["context_after"]) > 0
    assert "Счетчик" in hydrated["context_after"][0]


# ============================================================
# Test 6: JSON string "{}" is considered empty
# ============================================================
def test_json_string_empty_dict_is_empty():
    assert _is_empty_context("{}") == True
    assert _is_empty_context("[]") == True
    assert _is_empty_context("null") == True
    assert _is_empty_context("  ") == True
    assert _is_empty_context("") == True
    assert _is_empty_context(None) == True


# ============================================================
# Test 7: JSON-string row_data is parsed correctly
# ============================================================
def test_json_string_row_data_parsed():
    json_rd = json.dumps(PRODUCTION_ROW_DATA, ensure_ascii=False)
    c = _make_candidate(row_data=json_rd)
    hydrated = hydrate_candidate_context(c)
    assert "Светильник" in hydrated["matched_line"]


# ============================================================
# Test 8: Dict row_data is parsed correctly
# ============================================================
def test_dict_row_data_parsed():
    c = _make_candidate(row_data=PRODUCTION_ROW_DATA)
    hydrated = hydrate_candidate_context(c)
    assert "Светильник" in hydrated["matched_line"]
    assert len(hydrated["context_before"]) > 0
    assert len(hydrated["context_after"]) > 0


# ============================================================
# Test 9: Malformed row_data does not crash
# ============================================================
def test_malformed_row_data_no_crash():
    for bad_rd in [None, "", "not json at all", 42, True, "{broken"]:
        c = _make_candidate(row_data=bad_rd)
        hydrated = hydrate_candidate_context(c)
        # Should not crash, context may be empty
        assert "matched_line" in hydrated
        assert "context_before" in hydrated
        assert "context_after" in hydrated


# ============================================================
# Test 10: Nested table context is preserved (raw_cells formatting)
# ============================================================
def test_raw_cells_formatting_preserves_table():
    c = _make_candidate(
        matched_line="",
        row_data={
            "raw_cells": [
                {"col": "A", "text": "3"},
                {"col": "B", "text": "Светильник LED 40W"},
                {"col": "C", "text": "шт"},
                {"col": "D", "text": "120"},
            ],
            "context_before": [],
            "context_after": [],
        },
    )
    hydrated = hydrate_candidate_context(c)
    assert "Светильник LED 40W" in hydrated["matched_line"]
    assert "шт" in hydrated["matched_line"]
    assert "120" in hydrated["matched_line"]


# ============================================================
# Test 11: matched_line + before + after reach build_context_block
# ============================================================
def test_hydrated_context_reaches_build_context_block():
    captured_prompts = []

    def mock_ai(prompt):
        captured_prompts.append(prompt)
        return '{"detail_id": 99999, "decision": "UNKNOWN", "confidence": 0.0, "supporting_quote": "", "reason_code": "INSUFFICIENT_CONTEXT", "reason": "mock"}'

    validator = ContextValidator(ai_caller=mock_ai)
    c = _make_candidate(
        matched_line="",
        context_before={},
        context_after={},
        row_data=PRODUCTION_ROW_DATA,
    )

    block = validator.build_context_block(c)
    assert "Светильник" in block
    assert "Электрический щит" in block
    assert "Счетчик" in block


# ============================================================
# Test 12: Mocked AI caller receives hydrated context
# ============================================================
def test_mocked_ai_receives_hydrated_context():
    captured_prompts = []

    def mock_ai(prompt):
        captured_prompts.append(prompt)
        return '{"detail_id": 99999, "decision": "UNKNOWN", "confidence": 0.0, "supporting_quote": "", "reason_code": "INSUFFICIENT_CONTEXT", "reason": "mock"}'

    validator = ContextValidator(ai_caller=mock_ai)
    c = _make_candidate(
        matched_line="",
        context_before={},
        context_after={},
        row_data=PRODUCTION_ROW_DATA,
    )

    result = validator.validate_single(c)
    assert len(captured_prompts) == 1
    prompt_text = captured_prompts[0]
    assert "Светильник" in prompt_text, "Mocked AI must receive hydrated matched text"
    assert "Электрический щит" in prompt_text, "Mocked AI must receive hydrated context_before"


# ============================================================
# Test 13: No category/subcategory mutation
# ============================================================
def test_no_category_mutation():
    c = _make_candidate(
        category_code="waterproofing",
        subcategory_code="injection",
        row_data=PRODUCTION_ROW_DATA,
    )
    hydrated = hydrate_candidate_context(c)
    assert hydrated["category_code"] == "waterproofing"
    assert hydrated["subcategory_code"] == "injection"


# ============================================================
# Test 14: No Qwen call needed for hydration
# ============================================================
def test_hydration_no_model_call():
    """hydrate_candidate_context must NOT call any AI model."""
    import unittest.mock as mock

    with mock.patch("src.services.ai_client.generate") as mock_gen:
        c = _make_candidate(row_data=PRODUCTION_ROW_DATA)
        hydrated = hydrate_candidate_context(c)
        mock_gen.assert_not_called()


# ============================================================
# Test 15: _is_empty_context recognizes non-empty values
# ============================================================
def test_is_empty_context_non_empty():
    assert _is_empty_context(["line 1"]) == False
    assert _is_empty_context({"key": "val"}) == False
    assert _is_empty_context("some text") == False
    assert _is_empty_context(0) == False


# ============================================================
# Test 16: _format_raw_cells edge cases
# ============================================================
def test_format_raw_cells_edge_cases():
    assert _format_raw_cells(None) == ""
    assert _format_raw_cells([]) == ""
    assert _format_raw_cells([{"col": "A", "text": ""}]) == ""
    assert _format_raw_cells([{"col": "A", "text": "X"}, {"col": "B", "text": "Y"}]) == "X | Y"
    assert _format_raw_cells(["plain text"]) == "plain text"


# ============================================================
# Test 17: Row_data with matched_line key takes precedence over raw_cells
# ============================================================
def test_row_data_matched_line_key_over_raw_cells():
    c = _make_candidate(
        matched_line="",
        row_data={
            "matched_line": "SPECIFIC MATCHED LINE",
            "raw_cells": [
                {"col": "A", "text": "should not use this"},
            ],
            "context_before": [],
            "context_after": [],
        },
    )
    hydrated = hydrate_candidate_context(c)
    assert hydrated["matched_line"] == "SPECIFIC MATCHED LINE"


# ============================================================
# Test 18: Original candidate is not mutated
# ============================================================
def test_original_candidate_not_mutated():
    c = _make_candidate(
        matched_line="",
        context_before={},
        context_after={},
        row_data=PRODUCTION_ROW_DATA,
    )
    original_matched = c["matched_line"]
    original_before = c["context_before"]

    hydrated = hydrate_candidate_context(c)

    assert c["matched_line"] == original_matched, "Original must not be mutated"
    assert c["context_before"] is original_before, "Original must not be mutated"
    assert hydrated is not c, "Should return a new dict"
