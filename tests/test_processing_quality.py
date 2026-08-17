"""Unit tests for processing_quality service — no production PostgreSQL."""
from __future__ import annotations

import unittest

from src.services.processing_quality import (
    CATEGORY_AWARDED,
    CATEGORY_COMMISSION,
    CATEGORY_OPEN,
    CATEGORY_OTHER,
    WARN_DOMINANT_CATEGORY,
    WARN_EVIDENCE_SPIKE,
    WARN_HIGH_NO_LINKS,
    WARN_OPEN_STARVED,
    WARN_STUCK_PROCESSING,
    classify_table_source,
    compute_quality_metrics,
    compute_warnings,
)


class TestClassifyTableSource(unittest.TestCase):
    def test_open_44fz(self):
        self.assertEqual(classify_table_source("reestr_contract_44_fz"), CATEGORY_OPEN)

    def test_open_223fz(self):
        self.assertEqual(classify_table_source("reestr_contract_223_fz"), CATEGORY_OPEN)

    def test_awarded(self):
        self.assertEqual(classify_table_source("reestr_contract_44_fz_awarded"), CATEGORY_AWARDED)

    def test_completed_is_awarded(self):
        self.assertEqual(classify_table_source("reestr_contract_223_fz_completed"), CATEGORY_AWARDED)

    def test_commission_work_44(self):
        self.assertEqual(classify_table_source("reestr_contract_44_fz_commission_work"), CATEGORY_COMMISSION)

    def test_commission_work_223(self):
        self.assertEqual(classify_table_source("reestr_contract_223_fz_commission_work"), CATEGORY_COMMISSION)

    def test_615_pp(self):
        self.assertEqual(classify_table_source("reestr_contract_615_pp"), CATEGORY_COMMISSION)

    def test_615_pp_commission(self):
        self.assertEqual(classify_table_source("reestr_contract_615_pp_commission_work"), CATEGORY_COMMISSION)

    def test_unclear_is_other(self):
        self.assertEqual(classify_table_source("reestr_contract_44_fz_unclear"), CATEGORY_OTHER)

    def test_unknown_is_other(self):
        self.assertEqual(classify_table_source("reestr_contract_44_fz_unknown"), CATEGORY_OTHER)

    def test_bad_is_other(self):
        self.assertEqual(classify_table_source("reestr_contract_44_fz_bad"), CATEGORY_OTHER)

    def test_empty_string_is_other(self):
        self.assertEqual(classify_table_source(""), CATEGORY_OTHER)

    def test_none_is_other(self):
        self.assertEqual(classify_table_source(None), CATEGORY_OTHER)  # type: ignore[arg-type]

    def test_unknown_profile_is_other(self):
        self.assertEqual(classify_table_source("some_completely_unknown_table"), CATEGORY_OTHER)


class TestComputeQualityMetrics(unittest.TestCase):
    def _make_sbc(self, open_c=0, open_nl=0, open_e=0, award_c=0, comm_c=0):
        sbc = {}
        if open_c or open_nl or open_e:
            sbc[CATEGORY_OPEN] = {}
            if open_c:
                sbc[CATEGORY_OPEN]["completed"] = open_c
            if open_nl:
                sbc[CATEGORY_OPEN]["no_links"] = open_nl
            if open_e:
                sbc[CATEGORY_OPEN]["error"] = open_e
        if award_c:
            sbc[CATEGORY_AWARDED] = {"completed": award_c}
        if comm_c:
            sbc[CATEGORY_COMMISSION] = {"completed": comm_c}
        return sbc

    def test_no_links_rate(self):
        sbc = self._make_sbc(open_c=5, open_nl=5)
        m = compute_quality_metrics(status_by_category=sbc, match_rows=None, stuck_count=0)
        self.assertAlmostEqual(m.no_links_rate, 0.5)

    def test_error_rate(self):
        sbc = self._make_sbc(open_c=8, open_e=2)
        m = compute_quality_metrics(status_by_category=sbc, match_rows=None, stuck_count=0)
        self.assertAlmostEqual(m.error_rate, 0.2)

    def test_division_by_zero_no_links_rate(self):
        m = compute_quality_metrics(status_by_category={}, match_rows=None, stuck_count=0)
        self.assertIsNone(m.no_links_rate)
        self.assertIsNone(m.error_rate)

    def test_empty_data(self):
        m = compute_quality_metrics(status_by_category={}, match_rows=None, stuck_count=0)
        self.assertEqual(m.total_terminal, 0)
        self.assertEqual(m.completed, 0)
        self.assertFalse(m.match_data_available)

    def test_match_data_available_when_rows_given(self):
        sbc = self._make_sbc(open_c=10)
        rows = [{"registry_type": "reestr_contract_44_fz", "match_count": 5, "evidence_count": 20, "tender_count": 3}]
        m = compute_quality_metrics(status_by_category=sbc, match_rows=rows, stuck_count=0)
        self.assertTrue(m.match_data_available)
        self.assertEqual(m.total_matches, 5)
        self.assertEqual(m.total_evidence, 20)
        self.assertAlmostEqual(m.evidence_per_match, 4.0)
        self.assertAlmostEqual(m.matches_per_task, 0.5)

    def test_evidence_per_match_zero_matches(self):
        sbc = self._make_sbc(open_c=5)
        rows = [{"registry_type": "x", "match_count": 0, "evidence_count": 0, "tender_count": 0}]
        m = compute_quality_metrics(status_by_category=sbc, match_rows=rows, stuck_count=0)
        self.assertIsNone(m.evidence_per_match)

    def test_category_shares(self):
        sbc = {
            CATEGORY_OPEN: {"completed": 3},
            CATEGORY_AWARDED: {"completed": 7},
        }
        m = compute_quality_metrics(status_by_category=sbc, match_rows=None, stuck_count=0)
        self.assertAlmostEqual(m.category_shares[CATEGORY_OPEN], 0.3)
        self.assertAlmostEqual(m.category_shares[CATEGORY_AWARDED], 0.7)

    def test_unknown_table_source_maps_to_other(self):
        sbc = {"Другое": {"completed": 5}}
        m = compute_quality_metrics(status_by_category=sbc, match_rows=None, stuck_count=0)
        self.assertIn("Другое", m.by_category)


class TestComputeWarnings(unittest.TestCase):
    def _base(self, **kwargs):
        defaults = dict(
            no_links_rate=None,
            category_shares={},
            open_completed=10,
            evidence_per_match=None,
            stuck_count=0,
        )
        defaults.update(kwargs)
        return compute_warnings(**defaults)

    def test_no_links_high(self):
        ws = self._base(no_links_rate=0.6)
        codes = [w.code for w in ws]
        self.assertIn(WARN_HIGH_NO_LINKS, codes)

    def test_no_links_below_threshold(self):
        ws = self._base(no_links_rate=0.49)
        codes = [w.code for w in ws]
        self.assertNotIn(WARN_HIGH_NO_LINKS, codes)

    def test_no_links_rate_none_no_warning(self):
        ws = self._base(no_links_rate=None)
        codes = [w.code for w in ws]
        self.assertNotIn(WARN_HIGH_NO_LINKS, codes)

    def test_dominant_category(self):
        ws = self._base(category_shares={CATEGORY_AWARDED: 0.75})
        codes = [w.code for w in ws]
        self.assertIn(WARN_DOMINANT_CATEGORY, codes)

    def test_dominant_category_below_threshold(self):
        ws = self._base(category_shares={CATEGORY_AWARDED: 0.69})
        codes = [w.code for w in ws]
        self.assertNotIn(WARN_DOMINANT_CATEGORY, codes)

    def test_open_starved(self):
        ws = self._base(open_completed=3)
        codes = [w.code for w in ws]
        self.assertIn(WARN_OPEN_STARVED, codes)

    def test_open_not_starved(self):
        ws = self._base(open_completed=6)
        codes = [w.code for w in ws]
        self.assertNotIn(WARN_OPEN_STARVED, codes)

    def test_evidence_spike(self):
        ws = self._base(evidence_per_match=25.0)
        codes = [w.code for w in ws]
        self.assertIn(WARN_EVIDENCE_SPIKE, codes)

    def test_evidence_normal(self):
        ws = self._base(evidence_per_match=5.0)
        codes = [w.code for w in ws]
        self.assertNotIn(WARN_EVIDENCE_SPIKE, codes)

    def test_stuck_processing(self):
        ws = self._base(stuck_count=3)
        codes = [w.code for w in ws]
        self.assertIn(WARN_STUCK_PROCESSING, codes)

    def test_no_warnings_clean_state(self):
        ws = self._base(
            no_links_rate=0.1,
            category_shares={CATEGORY_OPEN: 0.5, CATEGORY_AWARDED: 0.4},
            open_completed=20,
            evidence_per_match=3.0,
            stuck_count=0,
        )
        self.assertEqual(ws, [])


if __name__ == "__main__":
    unittest.main()
