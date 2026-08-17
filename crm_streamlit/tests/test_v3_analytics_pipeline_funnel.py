"""Pipeline funnel labeling / NOT STARTED contract."""
from __future__ import annotations

from src.services.v3_analytics_pipeline_funnel import build_pipeline_funnel
from src.services.v3_analytics_service import V3AnalyticsSnapshot


def test_pipeline_funnel_separates_s7_and_s13_awarded() -> None:
    snap = V3AnalyticsSnapshot(
        source_44_open=10,
        source_223_open=20,
        source_44_waiting=1,
        source_223_waiting=2,
        source_44_awarded_all=50000,
        source_223_awarded_all=6000,
        source_open=30,
        source_waiting=3,
        s7_awarded_full_history_total=56000,
        crm_projected=14000,
        projected_open=12000,
        projected_waiting=20,
        projected_awarded_relevant=1115,
        full_historical_awarded_ignored=54885,
        okpd_business_funnel={
            "CONSTRUCTION_OKPD": 1,
            "DESIGN_PIR_OKPD": 2,
            "COMPUTERS_OKPD": 3,
            "LIGHTING_OKPD": 4,
            "OTHER_OKPD": 5,
            "MISSING_OKPD": 6,
        },
    )
    funnel = build_pipeline_funnel(snap)
    s7 = funnel["s7_source"]
    s13 = funnel["s13_projected"]
    assert s7["badge"].startswith("SOURCE: S7")
    assert s13["badge"].startswith("SOURCE: S13")
    assert s7["S7_AWARDED_FULL_HISTORY_TOTAL"] == 56000
    assert s13["PROJECTED_AWARDED_RELEVANT"] == 1115
    assert s13["FULL_HISTORICAL_AWARDED_IGNORED"] == 54885
    assert s7["S7_AWARDED_FULL_HISTORY_TOTAL"] > s13["PROJECTED_AWARDED_RELEVANT"]
    assert funnel["document_research"]["state"] == "NOT_STARTED"
    assert funnel["confirmed_medal"]["state"] == "NOT_STARTED"
    assert funnel["document_research"]["QUEUE_CREATED"] is None
    assert funnel["qwen_routing"]["model"] == "qwen2.5:7b"
