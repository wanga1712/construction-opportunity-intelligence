"""Test-only V3 analytics fixtures (not production golden procurements)."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Sequence

from src.domain.commercial_opportunity_lifecycle import CommercialOpportunityState
from src.domain.commercial_routing_v3 import CandidateMedal, OpportunityTrack, ProcurementForm
from src.services.commercial_routing_v3.projection import active_feed_includes_procurement


def _is_active(opportunities: Sequence[Dict[str, Any]]) -> bool:
    return active_feed_includes_procurement(list(opportunities), v3_schema_ready=True)

def build_fixture_opportunities() -> List[Dict[str, Any]]:
    return [
        {
            "id": "f1",
            "procurement_id": 1,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-LIGHT-1",
            "title": "Поставка светильников",
            "okpd": "27.40",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
            "candidate_medal": CandidateMedal.GOLD.value,
            "commercial_state": CommercialOpportunityState.ACTIVE.value,
            "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE.value,
        },
        {
            "id": "f2",
            "procurement_id": 2,
            "source_contour": "CORPORATE_223FZ",
            "contract_number": "223-PC-1",
            "title": "Поставка компьютеров",
            "okpd": "26.20",
            "category": "computers",
            "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
            "candidate_medal": CandidateMedal.SILVER.value,
            "commercial_state": CommercialOpportunityState.ACTIVE.value,
            "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE.value,
        },
        {
            "id": "f3",
            "procurement_id": 3,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-CONST-LIGHT",
            "title": "Строительство школы — освещение",
            "okpd": "41.00",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL.value,
            "candidate_medal": CandidateMedal.GOLD.value,
            "commercial_state": CommercialOpportunityState.ACTIVE.value,
            "procurement_form": ProcurementForm.CONSTRUCTION_WORKS.value,
        },
        {
            "id": "f4",
            "procurement_id": 4,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-DESIGN-1",
            "title": "Проектирование освещения",
            "okpd": "71.12",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.DESIGN_REQUIREMENT.value,
            "candidate_medal": CandidateMedal.BRONZE.value,
            "commercial_state": CommercialOpportunityState.ACTIVE.value,
            "procurement_form": ProcurementForm.DESIGN_ONLY.value,
        },
        {
            "id": "f5a",
            "procurement_id": 5,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-MULTI-1",
            "title": "Комплексная поставка",
            "okpd": "27.40",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
            "candidate_medal": CandidateMedal.GOLD.value,
            "commercial_state": CommercialOpportunityState.ACTIVE.value,
            "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE.value,
        },
        {
            "id": "f5b",
            "procurement_id": 5,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-MULTI-1",
            "title": "Комплексная поставка",
            "okpd": "26.20",
            "category": "computers",
            "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
            "candidate_medal": CandidateMedal.SILVER.value,
            "commercial_state": CommercialOpportunityState.ACTIVE.value,
            "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE.value,
        },
        {
            "id": "f6",
            "procurement_id": 6,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-DISC-1",
            "title": "Неизвестная категория",
            "okpd": "99.00",
            "category": None,
            "opportunity_track": OpportunityTrack.UNKNOWN.value,
            "candidate_medal": CandidateMedal.WOOD.value,
            "commercial_state": CommercialOpportunityState.REVIEW_REQUIRED.value,
            "procurement_form": ProcurementForm.UNKNOWN.value,
            "discovery_required": True,
        },
        {
            "id": "f7",
            "procurement_id": 7,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-WAIT-1",
            "title": "Ожидание итогов",
            "okpd": "27.40",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
            "candidate_medal": CandidateMedal.GOLD.value,
            "commercial_state": CommercialOpportunityState.WAITING_SOURCE_OUTCOME.value,
            "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE.value,
        },
        {
            "id": "f8",
            "procurement_id": 8,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-CLOSED-DIR",
            "title": "Закрытая прямая поставка",
            "okpd": "27.40",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.DIRECT_SUPPLY.value,
            "candidate_medal": CandidateMedal.GOLD.value,
            "commercial_state": CommercialOpportunityState.CLOSED.value,
            "procurement_form": ProcurementForm.DIRECT_GOODS_PURCHASE.value,
        },
        {
            "id": "f9",
            "procurement_id": 9,
            "source_contour": "PUBLIC_44FZ",
            "contract_number": "44-FOLLOW-1",
            "title": "Follow-up после awarded",
            "okpd": "41.00",
            "category": "lighting",
            "opportunity_track": OpportunityTrack.EMBEDDED_MATERIAL.value,
            "candidate_medal": CandidateMedal.GOLD.value,
            "commercial_state": CommercialOpportunityState.FOLLOW_UP_AWARDED.value,
            "procurement_form": ProcurementForm.CONSTRUCTION_WORKS.value,
        },
    ]


def summarize_fixture_analytics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    procurements = {r["procurement_id"] for r in rows}
    opportunities = len(rows)
    by_track_gold: Dict[str, int] = {}
    by_form: Dict[str, int] = {}
    by_lifecycle: Dict[str, int] = {}
    by_contour = {"44": 0, "223": 0}
    active_pids = set()
    discovery = 0
    for r in rows:
        tr = r.get("opportunity_track") or ""
        medal = r.get("candidate_medal")
        if medal == CandidateMedal.GOLD.value:
            by_track_gold[tr] = by_track_gold.get(tr, 0) + 1
        form = r.get("procurement_form") or ProcurementForm.UNKNOWN.value
        by_form[form] = by_form.get(form, 0) + 1
        st = r.get("commercial_state") or ""
        by_lifecycle[st] = by_lifecycle.get(st, 0) + 1
        if str(r.get("source_contour") or "").startswith("PUBLIC_44"):
            by_contour["44"] += 1
        elif "223" in str(r.get("source_contour") or ""):
            by_contour["223"] += 1
        if r.get("discovery_required") or r.get("category") is None:
            discovery += 1
        if _is_active([r]):
            active_pids.add(r["procurement_id"])

    cnt = Counter(r["procurement_id"] for r in rows)
    buckets = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    for _, n in cnt.items():
        if n == 1:
            buckets["1"] += 1
        elif n == 2:
            buckets["2"] += 1
        elif n == 3:
            buckets["3"] += 1
        else:
            buckets["4+"] += 1
    return {
        "unique_procurements": len(procurements),
        "total_opportunities": opportunities,
        "track_gold": by_track_gold,
        "forms": by_form,
        "lifecycle": by_lifecycle,
        "contour": by_contour,
        "active_leads": len(active_pids),
        "discovery": discovery,
        "multi_category": buckets,
        "avg_opportunities": round(opportunities / max(1, len(procurements)), 2),
    }
