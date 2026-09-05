#!/usr/bin/env python3
"""
Adds Zero-Slice Bug Regression Tests (Cases A, B, C, D, E) to test_context_validator_v3_trust_boundary.py.
"""
import os

TEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "test_context_validator_v3_trust_boundary.py",
)

with open(TEST_PATH, "r", encoding="utf-8") as f:
    src = f.read()

new_tests = '''

# 7. Zero-Slice Bug Regression Tests (Cases A, B, C, D, E)
def test_zero_slice_before_text_not_restored_by_negative_zero_index():
    """Case A: avail_before_net = 0 MUST yield used_before == "", NOT entire before_text."""
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    huge_before = ["СТРОКА_ДО_" + str(i) + " " + ("B" * 500) for i in range(100)] # ~50,000 chars
    candidate = {
        "detail_id": 901,
        "procurement_id": 901,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт." + ("M" * 1600),
        "context_before": huge_before,
        "context_after": [],
    }
    payload = validator.build_context_payload(candidate)
    vis_source = payload["visible_source_text"]
    block = payload["context_block"]

    # Case C: Context block length contract <= 3000
    assert len(block) <= 3000, f"context_block len={len(block)} exceeds max_context_chars=3000"

    # Case A & D: Entire huge before_text MUST NOT be in visible_source_text
    assert "СТРОКА_ДО_99" not in vis_source, "Truncated-out before_text MUST NOT be in visible_source_text"
    assert "СТРОКА_ДО_0" not in vis_source, "Truncated-out before_text MUST NOT be restored by [-0:] slice"


def test_zero_slice_after_text_not_restored_by_negative_zero_index():
    """Case B: avail_after_net = 0 MUST yield used_after == "", NOT entire after_text."""
    validator = ContextValidator(max_context_chars=3000, ai_caller=lambda p: "")
    huge_after = ["СТРОКА_ПОСЛЕ_" + str(i) + " " + ("A" * 500) for i in range(100)] # ~50,000 chars
    candidate = {
        "detail_id": 902,
        "procurement_id": 902,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт." + ("M" * 1600),
        "context_before": [],
        "context_after": huge_after,
    }
    payload = validator.build_context_payload(candidate)
    vis_source = payload["visible_source_text"]
    block = payload["context_block"]

    # Case C: Context block length contract <= 3000
    assert len(block) <= 3000, f"context_block len={len(block)} exceeds max_context_chars=3000"

    # Case B & D: Entire huge after_text MUST NOT be in visible_source_text
    assert "СТРОКА_ПОСЛЕ_99" not in vis_source, "Truncated-out after_text MUST NOT be in visible_source_text"


def test_quote_from_zero_slice_excluded_source_demoted_to_unknown():
    """Case E: Quote from excluded source text -> UNKNOWN / HALLUCINATED_QUOTE."""
    huge_before = ["СЕКРЕТНЫЙ_ДОКУМЕНТ_ДО_" + str(i) + " " + ("B" * 500) for i in range(100)]
    candidate = {
        "detail_id": 903,
        "category_code": "lighting",
        "subcategory_code": "road_street",
        "matched_term": "светильник",
        "matched_line": "Светильник уличный ДКУ 100 Вт." + ("M" * 1600),
        "context_before": huge_before,
        "context_after": [],
    }

    # Model attempts to quote text from excluded/truncated before_text
    def mock_caller_excluded_quote(p):
        return json.dumps({
            "detail_id": 903,
            "decision": "CONFIRMED",
            "confidence": 0.95,
            "supporting_quote": "СЕКРЕТНЫЙ_ДОКУМЕНТ_ДО_50",
            "reason": "Quoting excluded text",
        })

    validator = ContextValidator(ai_caller=mock_caller_excluded_quote)
    res = validator.validate_single(candidate)
    assert res["decision"] == "UNKNOWN"
    assert res["reason_code"] == "HALLUCINATED_QUOTE"
'''

assert "def test_strict_v3_evidence_provenance():" in src
src += new_tests

with open(TEST_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Successfully added zero-slice regression tests to test_context_validator_v3_trust_boundary.py")
