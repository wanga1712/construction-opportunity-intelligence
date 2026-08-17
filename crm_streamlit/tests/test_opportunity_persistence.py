from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.opportunity_persistence import (
    build_opportunity_rows,
    persist_category_opportunities,
)


class _FakeCrmDb:
    def __init__(self, *, table_exists: bool = True):
        self.table_exists = table_exists
        self.updates: List[tuple] = []

    def execute_scalar(self, sql: str, params: Optional[Any] = None) -> Any:
        if "to_regclass" in sql:
            return self.table_exists
        return None

    def execute_update(self, sql: str, params: Optional[Any] = None) -> None:
        self.updates.append((sql, params))


def test_build_opportunity_rows_from_v3_normalized_shape() -> None:
    normalized: Dict[str, Any] = {
        "source_contour": "PUBLIC_44FZ",
        "procurement_form": "DIRECT_GOODS_PURCHASE",
        "analysis_mode": "DIRECT_PRODUCT",
        "registry_version": 2,
        "registry_hash": "abc",
        "prompt_version": "v3",
        "routing_version": "v3",
        "model_name": "qwen2.5:7b",
    }
    opps = [
        {
            "category_code": "lighting",
            "subcategory_code": None,
            "opportunity_track": "DIRECT_SUPPLY",
            "confidence": 0.9,
            "research_action": "PRIORITY_DOCS",
            "commercial_priority_score": 85,
            "research_value_score": 70,
            "candidate_medal": "GOLD",
            "reason_codes": ["okpd_prior"],
            "negative_evidence": [],
        }
    ]
    rows = build_opportunity_rows(
        procurement_id=42,
        assessment_id=7,
        normalized_result=normalized,
        category_opportunities=opps,
    )
    assert len(rows) == 1
    assert rows[0]["commercial_category_code"] == "lighting"
    assert rows[0]["opportunity_track"] == "DIRECT_SUPPLY"
    assert rows[0]["candidate_medal"] == "GOLD"
    assert rows[0]["registry_hash"] == "abc"


def test_persist_dry_run_when_table_missing() -> None:
    db = _FakeCrmDb(table_exists=False)
    out = persist_category_opportunities(
        db,
        procurement_id=1,
        assessment_id=1,
        normalized_result={},
        category_opportunities=[],
        dry_run=True,
    )
    assert out["skipped"] is True
    assert out["persisted"] == 0
    assert db.updates == []


def test_persist_dry_run_returns_rows_without_writes() -> None:
    db = _FakeCrmDb(table_exists=True)
    out = persist_category_opportunities(
        db,
        procurement_id=1,
        assessment_id=1,
        normalized_result={
            "source_contour": "PUBLIC_44FZ",
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "analysis_mode": "DIRECT_PRODUCT",
            "routing_version": "v3",
        },
        category_opportunities=[
            {
                "category_code": "computers",
                "opportunity_track": "DIRECT_SUPPLY",
                "confidence": 0.8,
                "research_action": "LIGHT_RESEARCH",
                "candidate_medal": "SILVER",
            }
        ],
        dry_run=True,
    )
    assert out["dry_run"] is True
    assert out["persisted"] == 1
    assert db.updates == []
