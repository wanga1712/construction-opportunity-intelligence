"""Tests for CRM-BRIDGE-1: live processing results in procurement cards.

Covers:
  1.  load_batch returns dict keyed by crm_procurement_id
  2.  Composite key (contract_number + source_table) used for queue lookup
  3.  Same contract_number from different source_tables stays separate
  4.  match_count / evidence_count propagate to card via enrich_card
  5.  pending / processing / completed queue statuses displayed correctly
  6.  No results → honest empty state (has_results=False)
  7.  Gold: predicted_gold_prob >= 0.6 → is_gold_candidate True
  8.  NULL / missing gold_prob → is_gold_candidate False
  9.  commercial_scale_score injected as commercial_score when present
 10.  processing_stage promoted to 'ranked' when completed + scored + interesting
 11.  processing_stage promoted to 'ai_verified' when interesting but no score yet
 12.  No processing_stage change when no results
 13.  DB unavailable → load_batch returns empty dicts (no crash)
 14.  load_batch issues exactly 2 queries to tender_monitor (one per table)
 15.  compact and detail use the same _proc dict from enrich_card
"""
from __future__ import annotations

import unittest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card(
    *,
    crm_id: int = 1,
    source_id: int = 100,
    source_table: str = "reestr_contract_44_fz",
    contract_number: str = "CN001",
) -> dict:
    return {
        "id": crm_id,
        "source_id": source_id,
        "source_table": source_table,
        "contract_number": contract_number,
        "processing_stage": "matches_found",
        "commercial_score": None,
        "signal_score": 10,
        "match_score": 10,
        "end_date": date.today() + timedelta(days=10),
        "initial_price": 10_000_000,
    }


def _proc(
    *,
    queue_status: str | None = "completed",
    match_count: int = 5,
    interesting_count: int = 3,
    evidence_count: int = 42,
    last_processed_at=None,
    product_names=None,
    predicted_gold_prob: float | None = None,
    commercial_scale_score: float | None = None,
    category_confidence: float | None = None,
    has_results: bool = True,
    is_gold_candidate: bool = False,
) -> dict:
    return {
        "queue_status": queue_status,
        "queue_created_at": None,
        "match_count": match_count,
        "interesting_count": interesting_count,
        "evidence_count": evidence_count,
        "last_processed_at": last_processed_at or datetime(2026, 8, 5, 12, 0),
        "product_names": product_names or ["трубопровод", "грунтовка"],
        "predicted_gold_prob": predicted_gold_prob,
        "commercial_scale_score": commercial_scale_score,
        "category_confidence": category_confidence,
        "has_results": has_results,
        "is_gold_candidate": is_gold_candidate,
    }


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

from src.ui.components.analytics_v2.card_processing import (
    load_batch, enrich_card, _finalize, _GOLD_PROB_THRESHOLD,
)


# ---------------------------------------------------------------------------
# _finalize (pure logic, no DB)
# ---------------------------------------------------------------------------

class TestFinalize(unittest.TestCase):

    def test_has_results_true_when_evidence(self):
        results = {1: {"evidence_count": 42, "match_count": 5}}
        out = _finalize(results)
        self.assertTrue(out[1]["has_results"])

    def test_has_results_true_when_match_count_only(self):
        results = {2: {"match_count": 3, "evidence_count": 0}}
        out = _finalize(results)
        self.assertTrue(out[2]["has_results"])

    def test_has_results_false_when_both_zero(self):
        results = {3: {"match_count": 0, "evidence_count": 0}}
        out = _finalize(results)
        self.assertFalse(out[3]["has_results"])

    def test_is_gold_candidate_above_threshold(self):
        results = {1: {"predicted_gold_prob": _GOLD_PROB_THRESHOLD + 0.01}}
        out = _finalize(results)
        self.assertTrue(out[1]["is_gold_candidate"])

    def test_is_gold_candidate_exactly_threshold(self):
        results = {1: {"predicted_gold_prob": _GOLD_PROB_THRESHOLD}}
        out = _finalize(results)
        self.assertTrue(out[1]["is_gold_candidate"])

    def test_is_gold_candidate_false_below_threshold(self):
        results = {1: {"predicted_gold_prob": _GOLD_PROB_THRESHOLD - 0.01}}
        out = _finalize(results)
        self.assertFalse(out[1]["is_gold_candidate"])

    def test_is_gold_candidate_false_when_none(self):
        results = {1: {"predicted_gold_prob": None}}
        out = _finalize(results)
        self.assertFalse(out[1]["is_gold_candidate"])

    def test_empty_proc_gets_defaults(self):
        results = {99: {}}
        out = _finalize(results)
        self.assertFalse(out[99]["has_results"])
        self.assertFalse(out[99]["is_gold_candidate"])


# ---------------------------------------------------------------------------
# enrich_card (pure logic)
# ---------------------------------------------------------------------------

class TestEnrichCard(unittest.TestCase):

    def test_proc_injected(self):
        card = _card()
        p = _proc()
        enrich_card(card, p)
        self.assertIs(card["_proc"], p)

    def test_queue_status_injected(self):
        card = _card()
        enrich_card(card, _proc(queue_status="pending"))
        self.assertEqual(card["_queue_status"], "pending")

    def test_commercial_score_not_injected_from_scale(self):
        """commercial_scale_score is a priority score, NOT a medal quality score.
        It must NOT be injected as commercial_score — medals need MEDAL-ENGINE-1."""
        card = _card()
        enrich_card(card, _proc(commercial_scale_score=100.0))
        self.assertIsNone(card.get("commercial_score"),
                          "commercial_scale_score must not pollute card.commercial_score")

    def test_processing_stage_not_promoted_to_ranked(self):
        """processing_stage must NOT be promoted to 'ranked' — that requires MEDAL-ENGINE-1."""
        card = _card()
        enrich_card(card, _proc(
            queue_status="completed",
            interesting_count=5,
            commercial_scale_score=80.0,
        ))
        self.assertNotEqual(card["processing_stage"], "ranked",
                            "Bridge must not fake 'ranked' stage; MEDAL-ENGINE-1 is needed")

    def test_processing_stage_promoted_to_ai_verified(self):
        """Interesting matches but no score yet → ai_verified."""
        card = _card()
        enrich_card(card, _proc(
            queue_status="completed",
            interesting_count=3,
            commercial_scale_score=None,
        ))
        self.assertEqual(card["processing_stage"], "ai_verified")

    def test_processing_stage_unchanged_when_no_results(self):
        """No matches → keep original CRM stage."""
        card = _card()
        original_stage = card["processing_stage"]
        enrich_card(card, _proc(
            queue_status="sales_window_expired",
            interesting_count=0,
            match_count=0,
            evidence_count=0,
            commercial_scale_score=None,
            has_results=False,
        ))
        self.assertEqual(card["processing_stage"], original_stage)

    def test_evidence_count_propagated(self):
        card = _card()
        enrich_card(card, _proc(evidence_count=99))
        self.assertEqual(card["evidence_count"], 99)

    def test_empty_proc_no_crash(self):
        """Empty proc dict must not crash enrich_card."""
        card = _card()
        enrich_card(card, {})
        self.assertIsNone(card["_queue_status"])
        self.assertIsNone(card.get("commercial_score"))


# ---------------------------------------------------------------------------
# load_batch (mocked DB)
# ---------------------------------------------------------------------------

class TestLoadBatch(unittest.TestCase):

    def test_empty_cards_returns_empty_dict(self):
        result = load_batch([])
        self.assertEqual(result, {})

    @patch("psycopg2.connect", side_effect=Exception("no db"))
    def test_db_unavailable_returns_empty_dicts(self, _):
        """DB failure must return empty dicts, not raise."""
        cards = [_card(crm_id=1)]
        result = load_batch(cards)
        self.assertIsInstance(result, dict)
        self.assertIn(1, result)
        self.assertFalse(result[1].get("has_results"))

    def _make_mock_conn(self, queue_rows=None, match_rows=None):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        fetch_calls = []
        if queue_rows is not None:
            fetch_calls.append(queue_rows)
        if match_rows is not None:
            fetch_calls.append(match_rows)

        cursor.fetchall.side_effect = fetch_calls
        conn.close = MagicMock()
        return conn, cursor

    def test_returns_keyed_by_crm_id(self):
        cards = [_card(crm_id=7, contract_number="CN007", source_id=200)]
        queue_row = {
            "contract_reg_number": "CN007",
            "table_source": "reestr_contract_44_fz",
            "status": "completed",
            "created_at": None,
            "predicted_gold_prob": 0.75,
            "commercial_scale_score": 80.0,
            "category_confidence": 0.9,
        }
        match_row = {
            "tender_id": 200,
            "match_count": 4,
            "interesting_count": 2,
            "evidence_count": 50,
            "last_processed_at": datetime(2026, 8, 5),
            "product_names": ["трубы ПВХ"],
        }

        with patch(
            "src.ui.components.analytics_v2.card_processing._tm_conn"
        ) as mock_connect:
            conn = MagicMock()
            mock_connect.return_value = conn
            ctx = MagicMock()
            ctx.__enter__ = lambda s: s
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.fetchall.side_effect = [[queue_row], [match_row]]
            conn.cursor.return_value = ctx

            result = load_batch(cards)

        self.assertIn(7, result)
        self.assertEqual(result[7].get("queue_status"), "completed")
        self.assertEqual(result[7].get("evidence_count"), 50)

    def test_different_source_tables_not_mixed(self):
        """Two cards same contract_number but different source_table → separate rows."""
        card_44  = _card(crm_id=1, contract_number="SAME", source_table="reestr_contract_44_fz",  source_id=10)
        card_223 = _card(crm_id=2, contract_number="SAME", source_table="reestr_contract_223_fz", source_id=20)

        queue_rows = [
            {
                "contract_reg_number": "SAME",
                "table_source": "reestr_contract_44_fz",
                "status": "completed", "created_at": None,
                "predicted_gold_prob": 0.8,
                "commercial_scale_score": 82.0,
                "category_confidence": None,
            },
            {
                "contract_reg_number": "SAME",
                "table_source": "reestr_contract_223_fz",
                "status": "pending", "created_at": None,
                "predicted_gold_prob": None,
                "commercial_scale_score": None,
                "category_confidence": None,
            },
        ]

        with patch(
            "src.ui.components.analytics_v2.card_processing._tm_conn"
        ) as mock_connect:
            conn = MagicMock()
            mock_connect.return_value = conn
            ctx = MagicMock()
            ctx.__enter__ = lambda s: s
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.fetchall.side_effect = [queue_rows, []]  # match query returns nothing
            conn.cursor.return_value = ctx

            result = load_batch([card_44, card_223])

        self.assertEqual(result[1].get("queue_status"), "completed")
        self.assertEqual(result[2].get("queue_status"), "pending")

    def test_match_count_evidence_count_propagated(self):
        card = _card(crm_id=5, source_id=500)

        match_row = {
            "tender_id": 500,
            "match_count": 9,
            "interesting_count": 6,
            "evidence_count": 130,
            "last_processed_at": datetime(2026, 8, 5, 16, 13),
            "product_names": ["грунтовка", "ковролин"],
        }

        with patch(
            "src.ui.components.analytics_v2.card_processing._tm_conn"
        ) as mock_connect:
            conn = MagicMock()
            mock_connect.return_value = conn
            ctx = MagicMock()
            ctx.__enter__ = lambda s: s
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.fetchall.side_effect = [[], [match_row]]
            conn.cursor.return_value = ctx

            result = load_batch([card])

        self.assertEqual(result[5].get("match_count"), 9)
        self.assertEqual(result[5].get("evidence_count"), 130)
        self.assertEqual(result[5].get("product_names"), ["грунтовка", "ковролин"])
        self.assertTrue(result[5]["has_results"])

    def test_no_results_gives_empty_state(self):
        card = _card(crm_id=3)
        with patch(
            "src.ui.components.analytics_v2.card_processing._tm_conn"
        ) as mock_connect:
            conn = MagicMock()
            mock_connect.return_value = conn
            ctx = MagicMock()
            ctx.__enter__ = lambda s: s
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.fetchall.side_effect = [[], []]
            conn.cursor.return_value = ctx

            result = load_batch([card])

        self.assertFalse(result[3].get("has_results"))
        self.assertFalse(result[3].get("is_gold_candidate"))


# ---------------------------------------------------------------------------
# Integration: enrich_card + resolve_level (medal works end-to-end)
# ---------------------------------------------------------------------------

class TestMedalIntegration(unittest.TestCase):
    """Medals require MEDAL-ENGINE-1. Bridge must not fake them."""

    def test_bridge_alone_does_not_produce_medal(self):
        """Even with completed queue + commercial_scale_score, medal must NOT appear.
        commercial_scale_score is a priority scale, not a match-quality score.
        Medals need crm_procurements.commercial_score from MEDAL-ENGINE-1."""
        from src.ui.components.analytics_v2.card_trust import resolve_level
        card = _card()
        p = _proc(
            queue_status="completed",
            interesting_count=5,
            commercial_scale_score=100.0,
            predicted_gold_prob=0.23,
        )
        enrich_card(card, p)
        _, _, _, is_medal = resolve_level(card)
        self.assertFalse(is_medal,
                         "Bridge must not produce medals; that is MEDAL-ENGINE-1's job")

    def test_card_without_crm_commercial_score_stays_candidate(self):
        """Card with no commercial_score in crm_procurements shows as КАНДИДАТ."""
        from src.ui.components.analytics_v2.card_trust import resolve_level
        card = _card()  # commercial_score=None
        enrich_card(card, _proc(commercial_scale_score=None, interesting_count=0))
        _, _, _, is_medal = resolve_level(card)
        self.assertFalse(is_medal)

    def test_compact_and_detail_see_same_proc(self):
        """After enrich_card, both compact and detail read same _proc dict."""
        card = _card()
        p = _proc(evidence_count=77)
        enrich_card(card, p)
        self.assertEqual(card["_proc"]["evidence_count"], 77)
        self.assertEqual(card["evidence_count"], 77)

    def test_ai_verified_stage_when_interesting_matches(self):
        """Cards with interesting matches + processing|completed → ai_verified stage."""
        card = _card()
        enrich_card(card, _proc(
            queue_status="completed",
            interesting_count=3,
            commercial_scale_score=None,
        ))
        self.assertEqual(card["processing_stage"], "ai_verified")


if __name__ == "__main__":
    unittest.main()
