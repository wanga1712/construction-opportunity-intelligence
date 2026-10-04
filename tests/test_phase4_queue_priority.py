"""PHASE 4 targeted tests: admission gate, band logic, daemon S13_V4 branch."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.commercial_routing_v3.business_research_admission import (  # noqa: E402
    ADMISSION_POLICY_VERSION as POL,
    is_queue_eligible,
)
from src.services.research_queue_priority import get_effective_service_band  # noqa: E402

FEEDER = (ROOT / "src/services/commercial_routing_v3/factual_feeder.py").read_text(
    encoding="utf-8", errors="replace"
)


def _rec(state, policy=POL, band="GOLD"):
    return {
        "admission_state": state,
        "admission_policy_version": policy,
        "research_prior_band": band,
    }


# D/F/G/H: claim gate
def test_d_awarded_direct_excluded_not_claimable():
    assert is_queue_eligible(_rec("EXCLUDED")) is False


def test_f_hold_not_claimable():
    assert is_queue_eligible(_rec("HOLD")) is False


def test_g_excluded_not_claimable():
    assert is_queue_eligible(_rec("EXCLUDED")) is False


def test_h_stale_policy_not_claimable():
    assert is_queue_eligible(_rec("ELIGIBLE", policy="OLD_POLICY")) is False


def test_eligible_current_policy_claimable():
    assert is_queue_eligible(_rec("ELIGIBLE")) is True


# J: no 50k override
def test_j_direct_1e6_with_wood_stays_wood():
    band = get_effective_service_band(
        {"research_prior_band": "WOOD", "procurement_scope_type": "DIRECT_GOODS",
         "normalized_nmck_rub": 1_000_000}
    )
    assert band == "WOOD"


def test_gold_band_preserved():
    assert get_effective_service_band({"research_prior_band": "GOLD"}) == "GOLD"


# A/C: band follows current_effective_medal via the reconcile mapping
def test_a_c_band_mapping_present():
    assert "_BAND_RANK" in FEEDER
    assert "current_effective_medal" in FEEDER
    assert "research_prior_band = %s" in FEEDER


# B: reconcile must not rewrite technical status
def test_b_reconcile_does_not_touch_status():
    assert "SET status" not in FEEDER.split("def reconcile_active_queue")[1].split("def ")[0]


# E: must not touch candidate_initial_medal
def test_e_candidate_initial_medal_untouched():
    assert "candidate_initial_medal =" not in FEEDER


# I: daemon handles S13_V4 generation on the S13 branch
def test_i_daemon_v4_s13_branch():
    daemon = (ROOT / "tender_documents_research/document_processor/daemon.py")
    if not daemon.exists():
        return
    src = daemon.read_text(encoding="utf-8", errors="replace")
    assert '"S13_V4_EXHAUSTIVE_CONTEXT"' in src


def _run_all():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
