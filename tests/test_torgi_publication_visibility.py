"""Regression tests for authoritative torgi publication visibility (Phase 4)."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.services.torgi_publication import (
    TorgiHideReason,
    assessment_publication_status,
    has_visible_current_opportunity,
    is_confirmed_layer_visible,
    is_preliminary_ai_layer_visible,
    is_torgi_publication_visible,
    publication_schema_ready,
    source_lifecycle_allows_torgi,
)

_TODAY = date(2026, 8, 19)
_GOLDEN_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "reports"
    / "crm_v3_model_authority_restoration"
    / "GOLDEN_BAD_CASE_SNAPSHOT.json"
)
_EXPECTED_SHA = "e959ed6dd6a89d1e6adf2fc305e8ae6c12e01370957151489dbbcddb987f3d4c"


def _open_row(**kw):
    base = {
        "crm_stage": "torgi",
        "award_status": "submission_open",
        "end_date": _TODAY + timedelta(days=5),
        "ai_row": {
            "status": "SUCCESS",
            "normalized_result": {"business_scope_status": "IN_PROFILE"},
        },
        "opportunities": [
            {"status": "CURRENT", "commercial_state": "ACTIVE"},
        ],
    }
    base.update(kw)
    return base


def _visible(**kw) -> tuple[bool, TorgiHideReason | None]:
    row = _open_row(**kw)
    return is_torgi_publication_visible(
        crm_stage=row["crm_stage"],
        award_status=row["award_status"],
        end_date=row["end_date"],
        ai_row=row.get("ai_row"),
        opportunities=row.get("opportunities") or [],
        today=_TODAY,
    )


class TestTorgiPublicationContract:
    def test_open_projected_no_assessment_hidden(self):
        ok, reason = _visible(ai_row=None)
        assert ok is False
        assert reason == TorgiHideReason.UNASSESSED

    def test_unassessed_hidden(self):
        ok, reason = _visible(ai_row=None)
        assert ok is False
        assert reason == TorgiHideReason.UNASSESSED

    def test_failed_hidden(self):
        ok, reason = _visible(ai_row={"status": "FAILED", "normalized_result": {}})
        assert ok is False
        assert reason == TorgiHideReason.FAILED

    def test_incomplete_hidden(self):
        ok, reason = _visible(ai_row={"status": "SUCCESS", "normalized_result": None})
        assert ok is False
        assert reason == TorgiHideReason.INCOMPLETE

    def test_malformed_hidden(self):
        ok, reason = _visible(ai_row={"status": "SUCCESS", "normalized_result": {"foo": 1}})
        assert ok is False
        assert reason == TorgiHideReason.MALFORMED

    def test_assessed_no_opportunity_hidden(self):
        ok, reason = _visible(opportunities=[])
        assert ok is False
        assert reason == TorgiHideReason.NO_VISIBLE_OPPORTUNITY

    def test_assessed_non_visible_opportunity_hidden(self):
        ok, reason = _visible(
            opportunities=[{"status": "CURRENT", "commercial_state": "CLOSED"}]
        )
        assert ok is False
        assert reason == TorgiHideReason.NO_VISIBLE_OPPORTUNITY

    def test_valid_assessed_with_visible_opportunity_visible(self):
        ok, reason = _visible()
        assert ok is True
        assert reason is None

    def test_expired_procurement_hidden(self):
        ok, reason = is_torgi_publication_visible(
            crm_stage="torgi",
            award_status="submission_open",
            end_date=_TODAY - timedelta(days=1),
            ai_row={"status": "SUCCESS", "normalized_result": {"candidate_level": "WOOD"}},
            opportunities=[{"status": "CURRENT", "commercial_state": "ACTIVE"}],
            today=_TODAY,
        )
        assert ok is False
        assert reason == TorgiHideReason.SOURCE_LIFECYCLE

    def test_submission_closed_hidden(self):
        ok, reason = is_torgi_publication_visible(
            crm_stage="torgi",
            award_status="submission_closed_waiting_award",
            end_date=_TODAY + timedelta(days=3),
            ai_row={"status": "SUCCESS", "normalized_result": {"candidate_level": "WOOD"}},
            opportunities=[{"status": "CURRENT", "commercial_state": "ACTIVE"}],
            today=_TODAY,
        )
        assert ok is False
        assert reason == TorgiHideReason.SOURCE_LIFECYCLE

    def test_preliminary_excludes_unassessed(self):
        assert is_preliminary_ai_layer_visible(is_confirmed=False, publication_visible=False) is False

    def test_preliminary_excludes_no_opportunity(self):
        assert is_preliminary_ai_layer_visible(is_confirmed=False, publication_visible=False) is False

    def test_preliminary_includes_valid_unconfirmed(self):
        assert is_preliminary_ai_layer_visible(is_confirmed=False, publication_visible=True) is True

    def test_confirmed_requires_publication_visible(self):
        assert is_confirmed_layer_visible(is_confirmed=True, publication_visible=True) is True
        assert is_confirmed_layer_visible(is_confirmed=True, publication_visible=False) is False

    def test_old_confirmation_cannot_resurrect_expired(self):
        ok, _ = is_torgi_publication_visible(
            crm_stage="torgi",
            award_status="submission_open",
            end_date=_TODAY - timedelta(days=30),
            ai_row={"status": "SUCCESS", "normalized_result": {"candidate_level": "GOLD"}},
            opportunities=[{"status": "CURRENT", "commercial_state": "ACTIVE"}],
            today=_TODAY,
        )
        assert ok is False

    def test_fail_closed_on_schema_not_ready(self):
        ok, reason = is_torgi_publication_visible(
            crm_stage="torgi",
            award_status="submission_open",
            end_date=_TODAY + timedelta(days=2),
            ai_row={"status": "SUCCESS", "normalized_result": {"candidate_level": "GOLD"}},
            opportunities=[{"status": "CURRENT", "commercial_state": "ACTIVE"}],
            v3_schema_ready=False,
            today=_TODAY,
        )
        assert ok is False
        assert reason == TorgiHideReason.SCHEMA_NOT_READY

    def test_publication_schema_ready_fail_closed(self):
        class _Db:
            def execute_scalar(self, _sql):
                return False

            def execute_query(self, *_a, **_k):
                return []

        assert publication_schema_ready(_Db()) is False


class TestGoldenVisibilityRegression:
    @pytest.fixture(scope="class")
    def golden(self):
        raw = _GOLDEN_PATH.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        assert data.get("GOLDEN_SNAPSHOT_SHA256") == _EXPECTED_SHA
        return data

    def _case_visible(self, case: dict) -> tuple[bool, TorgiHideReason | None]:
        end = case.get("end_date")
        end_date = date.fromisoformat(end) if end else None
        ai = case.get("assessment")
        ai_row = None
        if ai:
            ai_row = {
                "status": ai.get("status"),
                "normalized_result": ai.get("normalized_result"),
            }
        elif case.get("effective_assessment", {}).get("ai_status") == "UNASSESSED":
            ai_row = None
        return is_torgi_publication_visible(
            crm_stage=case.get("crm_stage") or "",
            award_status=case.get("award_status") or "",
            end_date=end_date,
            ai_row=ai_row,
            opportunities=case.get("opportunities") or [],
            today=_TODAY,
        )

    def test_golden_snapshot_hash_unchanged(self, golden):
        assert golden["GOLDEN_SNAPSHOT_SHA256"] == _EXPECTED_SHA
        assert golden["GOLDEN_CASES_TOTAL"] == 67

    def test_golden_expected_visibility_match(self, golden):
        unexpected_hides = []
        unexpected_visible = []
        for case in golden["cases"]:
            visible, reason = self._case_visible(case)
            exp = case["expected_post_fix"]
            if exp == "SHOULD_HIDE_NO_AI" or any(
                "failed" in str(g).lower() for g in (case.get("snapshot_groups") or [])
            ):
                if visible:
                    unexpected_visible.append(case["procurement_id"])
            elif exp in ("SHOULD_REMAIN_VISIBLE_VALID_AI", "REQUIRES_REASSESSMENT"):
                has_opp = has_visible_current_opportunity(case.get("opportunities") or [])
                if has_opp and not visible:
                    unexpected_hides.append((case["procurement_id"], reason))
                if not has_opp and visible:
                    unexpected_visible.append(case["procurement_id"])
            elif exp == "SHOULD_REMAIN_VISIBLE_CONFIRMED":
                # Closed/expired lifecycle — not in open torgi feed regardless
                pass
        assert unexpected_hides == [], f"unexpected hides: {unexpected_hides}"
        assert unexpected_visible == [], f"unexpected visible: {unexpected_visible}"


def test_assessment_publication_status_error():
    ok, reason = assessment_publication_status(ai_row={"status": "ERROR", "normalized_result": {}})
    assert ok is False and reason == TorgiHideReason.FAILED


def test_source_lifecycle_allows_torgi_open_only():
    assert source_lifecycle_allows_torgi(
        crm_stage="torgi",
        award_status="submission_open",
        end_date=_TODAY,
        today=_TODAY,
    )
    assert not source_lifecycle_allows_torgi(
        crm_stage="torgi",
        award_status="awarded",
        end_date=_TODAY,
        today=_TODAY,
    )
