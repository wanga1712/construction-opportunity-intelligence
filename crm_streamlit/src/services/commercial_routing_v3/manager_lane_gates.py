"""Separate ACTIVE / AWARDED human launch ranking gates.

Manager workbench has two lanes. Mixed global Top-N is not launch evidence.
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.services.commercial_routing_v3.manager_object_ranking import (
    WorkbenchCommercialState,
    rank_manager_objects,
)

LANE_ACTIVE = "ACTIVE"
LANE_AWARDED = "AWARDED"


def _rerank(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked, _ = rank_manager_objects(rows)
    for i, obj in enumerate(ranked, 1):
        obj["lane_rank"] = i
    return ranked


def split_actionable_lanes(
    objects: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    actionable, _closed = rank_manager_objects(objects)
    active = [
        o
        for o in actionable
        if str(o.get("workbench_status") or "")
        == WorkbenchCommercialState.PREQUALIFIED_ACTIVE.value
    ]
    awarded = [
        o
        for o in actionable
        if str(o.get("workbench_status") or "")
        == WorkbenchCommercialState.PREQUALIFIED_AWARDED.value
    ]
    active = _rerank(active)
    awarded = _rerank(awarded)
    return {
        "ACTIONABLE_ACTIVE": active,
        "ACTIONABLE_AWARDED": awarded,
        "TOP_10_ACTIVE": active[:10],
        "TOP_5_ACTIVE": active[:5],
        "TOP_10_AWARDED": awarded[:10],
        "TOP_5_AWARDED": awarded[:5],
    }
