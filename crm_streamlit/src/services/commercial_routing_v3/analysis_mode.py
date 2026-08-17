"""Analysis mode derivation from procurement form."""
from __future__ import annotations

from typing import List

from src.domain.commercial_routing_v3 import (
    AnalysisMode,
    PROCUREMENT_FORM_DEFAULT_ANALYSIS,
    ProcurementForm,
)


def resolve_analysis_modes(procurement_form: ProcurementForm) -> List[AnalysisMode]:
    return list(PROCUREMENT_FORM_DEFAULT_ANALYSIS.get(procurement_form, [AnalysisMode.GENERAL_DISCOVERY]))
