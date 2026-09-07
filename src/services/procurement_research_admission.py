"""Procurement-grain business admission before document research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.learning.procurement_scope.classifier import ProcurementScopeType


@dataclass(frozen=True)
class ResearchAdmission:
    lifecycle: str
    scope_type: str
    state: str
    reason: str


def lifecycle_for(procurement: Mapping[str, Any]) -> str:
    stage = str(procurement.get("crm_stage") or "").lower()
    award = str(procurement.get("award_status") or "").lower()
    if stage == "torgi" and award == "submission_open":
        return "OPEN"
    if stage == "razygranye" or award == "awarded":
        return "AWARDED"
    if stage == "torgi" and award == "submission_closed_waiting_award":
        return "WAITING_AWARD"
    return "UNKNOWN_LIFECYCLE"


def evaluate_admission(procurement: Mapping[str, Any], scope_type: str) -> ResearchAdmission:
    lifecycle = lifecycle_for(procurement)
    scope = str(scope_type or ProcurementScopeType.UNKNOWN.value)
    if lifecycle == "WAITING_AWARD":
        return ResearchAdmission(lifecycle, scope, "HOLD", "WAITING_FOR_AWARD")
    if lifecycle == "UNKNOWN_LIFECYCLE":
        return ResearchAdmission(lifecycle, scope, "HOLD", "UNKNOWN_LIFECYCLE")
    if scope == ProcurementScopeType.UNKNOWN.value:
        return ResearchAdmission(lifecycle, scope, "HOLD", "UNKNOWN_SCOPE")
    if scope == ProcurementScopeType.PURE_SERVICE.value:
        return ResearchAdmission(lifecycle, scope, "EXCLUDED", "PURE_SERVICE")
    if lifecycle == "AWARDED" and scope == ProcurementScopeType.DIRECT_GOODS.value:
        return ResearchAdmission(lifecycle, scope, "EXCLUDED", "AWARDED_DIRECT_GOODS")
    return ResearchAdmission(lifecycle, scope, "ELIGIBLE", "CURRENT_BUSINESS_ADMISSION")
