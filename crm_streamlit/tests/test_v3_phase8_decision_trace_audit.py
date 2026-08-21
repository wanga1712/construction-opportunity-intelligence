"""Phase 8 audit artifact contract (no production behavior change)."""
from __future__ import annotations

import json
from pathlib import Path

REP = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "reports"
    / "crm_v3_model_authority_restoration"
)


def test_phase8_decision_trace_artifacts_present():
    required = [
        "MODEL_DECISION_TRACE_AUDIT.md",
        "MODEL_INPUT_FIELD_AUDIT.md",
        "MODEL_QUESTION_DECOMPOSITION.md",
        "MODEL_POSTPROCESSING_PROVENANCE.md",
        "model_decision_trace_cases.json",
    ]
    for name in required:
        assert (REP / name).is_file(), name


def test_phase8_cases_json_contract():
    data = json.loads((REP / "model_decision_trace_cases.json").read_text(encoding="utf-8"))
    assert data["phase"] == "8"
    assert data["TRACED_CASES"] >= 34
    assert data["DIRECT_CASES"] >= 10
    assert data["NEGATIVE_CASES"] >= 10
    assert data["OBJECT_CASES"] >= 10
    assert data["CASE_37082_PRIMARY_ROOT_CAUSE"] == "CATEGORY_MAPPING_ERROR"
    assert data["CASE_23591_PRIMARY_ROOT_CAUSE"] == "ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"
    assert (
        data["compare_37082_vs_23591"]["DO_37082_AND_23591_SHARE_THE_SAME_FAILURE_MECHANISM"]
        == "NO"
    )
    assert data["MODEL_VALIDATED_MUTATED"] == "NO"
    assert data["PRODUCTION_PROMPT_CHANGED"] == "NO"
    assert data["document_boundary"]["DOCUMENT_CONTENT_SENT_TO_ROUTING_MODEL"] == "NO"
    assert data["semantic_split"]["ACTUAL_PURCHASE_VS_REGISTRY_MAPPING_MIXED"] == "YES"
    pids = {c["procurement_id"] for c in data["cases"]}
    assert {37082, 23591, 27355, 34517}.issubset(pids)
    c235 = next(c for c in data["cases"] if c["procurement_id"] == 23591)
    assert c235["flags"]["ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR"] == "YES"
    assert c235["flags"]["CATEGORY_MAPPING_ERROR"] == "NO"
    assert c235["RAW_CATEGORY"] == "cable"
    assert c235["VALIDATED_CATEGORY"] is None
