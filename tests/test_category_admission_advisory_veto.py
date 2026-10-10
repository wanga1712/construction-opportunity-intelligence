from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.commercial_routing_v3.category_admission import (  # noqa: E402
    SIGNAL_DIRECT_PRODUCT_EVIDENCE,
    SIGNAL_NONE,
    has_admissible_category_signal,
)
from src.services.commercial_routing_v3.category_hard_veto import (  # noqa: E402
    REASON_ROAD_WORKS_OUT_OF_CATEGORY,
)

VETO_TITLE = "Устройство асфальтобетонного покрытия"


def test_advisory_veto_does_not_create_admission():
    hypothesis = {"category_code": "lighting"}
    admissible, signal = has_admissible_category_signal(
        hypothesis, title=VETO_TITLE
    )
    assert admissible is False
    assert signal == SIGNAL_NONE
    assert hypothesis["veto_hint"] == REASON_ROAD_WORKS_OUT_OF_CATEGORY


def test_advisory_veto_does_not_block_real_admission_signal():
    hypothesis = {
        "category_code": "lighting",
        "direct_product_evidence_sources": ["independent_source"],
    }
    admissible, signal = has_admissible_category_signal(
        hypothesis, title=VETO_TITLE
    )
    assert admissible is True
    assert signal == SIGNAL_DIRECT_PRODUCT_EVIDENCE
    assert hypothesis["veto_hint"] == REASON_ROAD_WORKS_OUT_OF_CATEGORY
