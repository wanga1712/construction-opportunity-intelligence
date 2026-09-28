"""Phase 6.3 — deterministic shadow eligibility gate (pure logic; no DB, no model)."""
import datetime as dt
import unittest

from src.services.commercial_routing_v3.shadow_predictor import (
    classify_shadow_eligibility,
)
from src.services.commercial_routing_v3.submission_window import (
    MIN_REMAINING_SUBMISSION_DAYS,
)


def _row(stage, award, days_from_today):
    return (stage, award, dt.date.today() + dt.timedelta(days=days_from_today))


class ShadowEligibilityGateTests(unittest.TestCase):
    def test_live_actionable_at_boundary_is_eligible(self):
        row = _row("torgi", "submission_open", MIN_REMAINING_SUBMISSION_DAYS)
        self.assertIsNone(classify_shadow_eligibility(row))

    def test_live_actionable_far_future_is_eligible(self):
        row = _row("torgi", "submission_open", 30)
        self.assertIsNone(classify_shadow_eligibility(row))

    def test_short_window_is_skipped(self):
        row = _row("torgi", "submission_open", MIN_REMAINING_SUBMISSION_DAYS - 1)
        self.assertEqual("NON_ACTIONABLE_WINDOW_LT2D", classify_shadow_eligibility(row))

    def test_expired_is_skipped(self):
        row = _row("torgi", "submission_open", -30)
        self.assertTrue(
            classify_shadow_eligibility(row).startswith("NON_ACTIONABLE_WINDOW_LT")
        )

    def test_awarded_is_skipped(self):
        self.assertEqual(
            "NON_ACTIONABLE_AWARDED",
            classify_shadow_eligibility(_row("torgi", "awarded", 30)),
        )

    def test_closed_waiting_is_skipped(self):
        self.assertEqual(
            "NON_ACTIONABLE_SUBMISSION_CLOSED",
            classify_shadow_eligibility(
                _row("torgi", "submission_closed_waiting_award", 30)
            ),
        )

    def test_non_torgi_stage_is_skipped(self):
        self.assertEqual(
            "NON_ACTIONABLE_NON_TORGI_STAGE",
            classify_shadow_eligibility(_row("razygranye", "awarded", 30)),
        )

    def test_commission_is_skipped(self):
        self.assertEqual(
            "NON_ACTIONABLE_COMMISSION",
            classify_shadow_eligibility(_row("commission", "commission", 30)),
        )

    def test_missing_lifecycle_is_skipped(self):
        self.assertEqual("MISSING_LIFECYCLE", classify_shadow_eligibility(None))

    def test_unknown_award_status_is_skipped(self):
        self.assertEqual(
            "NON_ACTIONABLE_AWARD_STATUS",
            classify_shadow_eligibility(_row("torgi", "weird_status", 30)),
        )


if __name__ == "__main__":
    unittest.main()