"""Targeted tests: ADMISSION-GATE-RUNTIME-ENFORCEMENT-1 (BUSINESS_RESEARCH_ADMISSION_V2).

Scope: only authority -> producer -> reconciliation -> claim -> awarded UI.
No broad project suite. No DB writes. No Qwen. No downloads.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.services.commercial_routing_v3.business_research_admission import (
    ADMISSION_POLICY_VERSION as POL,
    ELIGIBLE,
    EXCLUDED,
    HOLD,
    decide_admission,
    is_queue_eligible,
)


def _rec(state, **extra):
    rec = {"admission_state": state, "admission_policy_version": POL}
    rec.update(extra)
    return rec


# A. OPEN DIRECT -> ELIGIBLE
def test_a_open_direct_eligible():
    assert decide_admission("OPEN", "DIRECT_GOODS")[0] == ELIGIBLE


# B. AWARDED DIRECT -> EXCLUDED
def test_b_awarded_direct_excluded():
    assert decide_admission("AWARDED", "DIRECT_GOODS") == (EXCLUDED, "AWARDED_DIRECT_GOODS")


# C. AWARDED WORKS -> ELIGIBLE
def test_c_awarded_works_eligible():
    assert decide_admission("AWARDED", "WORKS_WITH_EMBEDDED_PRODUCTS")[0] == ELIGIBLE


# D. AWARDED DESIGN -> ELIGIBLE
def test_d_awarded_design_eligible():
    assert decide_admission("AWARDED", "DESIGN_PROJECT")[0] == ELIGIBLE


# E. WAITING_AWARD -> HOLD
def test_e_waiting_award_hold():
    for scope in ("DIRECT_GOODS", "WORKS_WITH_EMBEDDED_PRODUCTS", "DESIGN_PROJECT"):
        assert decide_admission("WAITING_SOURCE_OUTCOME", scope) == (HOLD, "WAITING_FOR_AWARD")


def test_open_variants_eligible():
    for scope in ("DIRECT_GOODS", "WORKS_WITH_EMBEDDED_PRODUCTS", "DESIGN_PROJECT"):
        assert decide_admission("OPEN", scope)[0] == ELIGIBLE


def test_non_business_scope_holds():
    for scope in ("PURE_SERVICE", "EQUIPMENT_AND_INSTALLATION", "MIXED", "UNKNOWN"):
        assert decide_admission("OPEN", scope)[0] == HOLD


# F. EXCLUDED queue row -> claim impossible
def test_f_excluded_row_claim_impossible():
    assert is_queue_eligible(_rec(EXCLUDED)) is False


# G. HOLD queue row -> claim impossible
def test_g_hold_row_claim_impossible():
    assert is_queue_eligible(_rec(HOLD)) is False


# H. GOLD + EXCLUDED -> claim impossible
def test_h_gold_excluded_claim_impossible():
    assert is_queue_eligible(_rec(EXCLUDED, research_prior_band="GOLD", priority_score=100)) is False


def test_eligible_requires_current_policy():
    assert is_queue_eligible(_rec(ELIGIBLE)) is True
    assert is_queue_eligible(None) is False
    assert is_queue_eligible({"admission_state": ELIGIBLE}) is False
    assert is_queue_eligible({"admission_state": ELIGIBLE, "admission_policy_version": "STALE"}) is False


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TENDER_ROOT = Path(os.getenv("TENDER_DOCS_ROOT", "/opt/tender_documents_research"))
TENDER_REPO = _TENDER_ROOT / "document_processor/backends/queue_repository.py"
TABS = _REPO_ROOT / "src/ui/components/analytics_v2/tabs.py"


# F/G/H applied: claim gate present in both claim paths
@pytest.mark.skipif(not TENDER_REPO.exists(), reason="tender repo not present")
def test_claim_gate_present_in_both_paths():
    src = TENDER_REPO.read_text(encoding="utf-8", errors="replace")
    assert "admission_state' = 'ELIGIBLE'" in src
    assert POL in src
    assert "{_ADMISSION_FILTER}" in src      # legacy claim path
    assert "+ _ADMISSION_FILTER" in src      # DWRR two-phase pool filter


# I/J. awarded UI workset requires a current ELIGIBLE decision
def test_awarded_ui_requires_eligible():
    if not TABS.exists():
        pytest.skip(f"tabs.py not found at {TABS}")
    src = TABS.read_text(encoding="utf-8", errors="replace")
    assert "crm_procurement_scope_authority" in src
    assert "sa.admission_state = 'ELIGIBLE'" in src
    assert POL in src
    assert "_AWARDED_ADMISSION_SQL" in src
