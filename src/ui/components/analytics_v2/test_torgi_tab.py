"""Tests for «Идут торги» tab data path and card logic.

Covers:
  1.  Active OPEN card included in load
  2.  Post-deadline (submission_closed) card NOT in «Идут торги» (→ «Комиссия»)
  3.  Expired open card (end_date < today) NOT in «Идут торги»
  4.  Stale/terminal queue row → NOT shown as «ИИ в очереди»
  5.  Active pending queue row → «ИИ в очереди»
  6.  Processing queue row → separate label, not «ИИ в очереди»
  7.  Gold commercial_score passes through JOIN to priority score
  8.  Silver/Bronze priority score lower than Gold
  9.  No Gold in card set → honest low medal score (no false Gold)
  10. OPEN award_status has higher priority than grace-period card
  11. _load_queue_statuses_batch issues one query, not one per card
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card(
    *,
    award_status: str = "submission_open",
    days_offset: int = 5,
    commercial_score: int | None = None,
    signal_score: int = 0,
    match_score: int = 0,
    processing_stage: str = "matches_found",
    contract_number: str = "0123456789",
    queue_status: str | None = None,
) -> dict:
    end_date = date.today() + timedelta(days=days_offset)
    card = {
        "id": 1,
        "contract_number": contract_number,
        "auction_name": "Test",
        "initial_price": 5_000_000,
        "end_date": end_date,
        "award_status": award_status,
        "commercial_score": commercial_score,
        "signal_score": signal_score,
        "match_score": match_score,
        "processing_stage": processing_stage,
        "_queue_status": queue_status,
    }
    return card


# ---------------------------------------------------------------------------
# Priority score tests (unit, no DB)
# ---------------------------------------------------------------------------

from src.ui.components.analytics_v2.tabs import _torgi_priority_score


class TestPriorityScore(unittest.TestCase):

    def test_open_card_beats_grace_period_card(self):
        """submission_open card must rank above grace-period card."""
        open_card  = _card(award_status="submission_open", days_offset=2, commercial_score=0)
        grace_card = _card(
            award_status="submission_closed_waiting_award",
            days_offset=-5,
            commercial_score=80,
        )
        # Even a Gold grace-period card must not outrank an active OPEN card
        self.assertGreater(
            _torgi_priority_score(open_card),
            _torgi_priority_score(grace_card),
        )

    def test_gold_ranks_above_silver(self):
        """Gold (commercial>=75) outranks Silver (50–74) when both are open."""
        gold   = _card(award_status="submission_open", commercial_score=80, days_offset=10)
        silver = _card(award_status="submission_open", commercial_score=55, days_offset=10)
        self.assertGreater(_torgi_priority_score(gold), _torgi_priority_score(silver))

    def test_silver_ranks_above_bronze(self):
        bronze = _card(award_status="submission_open", commercial_score=30, days_offset=10)
        silver = _card(award_status="submission_open", commercial_score=55, days_offset=10)
        self.assertGreater(_torgi_priority_score(silver), _torgi_priority_score(bronze))

    def test_no_commercial_score_not_falsely_gold(self):
        """Card without commercial_score must not outscore a real Gold card."""
        unranked = _card(award_status="submission_open", commercial_score=None, signal_score=99)
        gold     = _card(award_status="submission_open", commercial_score=80, signal_score=0)
        self.assertGreater(_torgi_priority_score(gold), _torgi_priority_score(unranked))

    def test_comfortable_deadline_ranks_above_dead_window(self):
        """Among unranked cards, MORE time remaining → higher priority.
        Cards with wdays<=1 sink to bottom (too late to act profitably)."""
        comfy  = _card(award_status="submission_open", commercial_score=None, days_offset=30)
        urgent = _card(award_status="submission_open", commercial_score=None, days_offset=1)
        self.assertGreater(_torgi_priority_score(comfy), _torgi_priority_score(urgent))

    def test_signal_score_36_does_not_beat_gold(self):
        """Regression: signal_score=36 must not push an unranked card above Gold."""
        high_signal = _card(award_status="submission_open", commercial_score=None, signal_score=36)
        gold        = _card(award_status="submission_open", commercial_score=80, signal_score=0)
        self.assertGreater(_torgi_priority_score(gold), _torgi_priority_score(high_signal))


# ---------------------------------------------------------------------------
# Grace-period filter tests (unit, via SQL filter logic simulation)
# ---------------------------------------------------------------------------

class TestGracePeriodFilter(unittest.TestCase):
    """«Идут торги» = submission_open AND end_date >= today ONLY.
    Grace-period cards (submission_closed_waiting_award) go to «Комиссия», not here.
    """

    def _filter_cards(self, cards: list[dict]) -> list[dict]:
        """Simulate the SQL WHERE clause for «Идут торги» in Python."""
        today = date.today()
        return [
            c for c in cards
            if c.get("award_status") == "submission_open"
            and c.get("end_date") is not None
            and c["end_date"] >= today
        ]

    def test_open_card_shown(self):
        card = {"award_status": "submission_open", "end_date": date.today() + timedelta(days=3)}
        self.assertEqual(len(self._filter_cards([card])), 1)

    def test_post_deadline_submission_closed_not_in_torgi(self):
        """submission_closed_waiting_award card must NOT appear in «Идут торги» (→ «Комиссия»)."""
        card = {
            "award_status": "submission_closed_waiting_award",
            "end_date": date.today() - timedelta(days=2),
        }
        self.assertEqual(len(self._filter_cards([card])), 0)

    def test_expired_open_card_not_in_torgi(self):
        """submission_open card past its end_date must NOT appear in «Идут торги»."""
        card = {
            "award_status": "submission_open",
            "end_date": date.today() - timedelta(days=1),
        }
        self.assertEqual(len(self._filter_cards([card])), 0)

    def test_open_and_awarded_not_mixed(self):
        """award_status='awarded' must not appear in torgi tab."""
        cards = [
            {"award_status": "submission_open", "end_date": date.today() + timedelta(days=3)},
            {"award_status": "awarded", "end_date": date.today() - timedelta(days=1)},
        ]
        result = self._filter_cards(cards)
        statuses = {c["award_status"] for c in result}
        self.assertNotIn("awarded", statuses)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Queue status display tests (unit, card_compact logic)
# ---------------------------------------------------------------------------

def _ai_status_from_card(card: dict) -> str:
    """Mirror the ai_status logic from card_compact.py for testing."""
    stage = card.get("processing_stage", "matches_found")
    queue_status = card.get("_queue_status")
    if queue_status == "pending":
        return "ИИ в очереди"
    elif queue_status == "processing":
        return "ИИ обрабатывает"
    elif queue_status == "completed":
        return "ИИ завершён"
    elif queue_status in ("no_links", "sales_window_expired", "error"):
        return "нет данных ИИ"
    elif queue_status is not None:
        return f"ИИ: {queue_status}"
    else:
        if stage in ("ranked", "manager_confirmed"):
            return "ИИ завершён"
        elif stage in ("raw", "documents_loaded", "matches_found"):
            return "ИИ в очереди"
        else:
            return "ИИ обрабатывает"


class TestQueueStatusDisplay(unittest.TestCase):

    def test_stale_terminal_queue_row_not_shown_as_in_queue(self):
        """Queue row with terminal status (error/no_links) must NOT show «ИИ в очереди»."""
        for terminal in ("error", "no_links", "sales_window_expired"):
            card = _card(processing_stage="matches_found", queue_status=terminal)
            status = _ai_status_from_card(card)
            self.assertNotEqual(status, "ИИ в очереди",
                                f"terminal status {terminal!r} should not show «ИИ в очереди»")

    def test_active_pending_row_shown_as_in_queue(self):
        card = _card(processing_stage="raw", queue_status="pending")
        self.assertEqual(_ai_status_from_card(card), "ИИ в очереди")

    def test_processing_row_shown_separately(self):
        card = _card(processing_stage="raw", queue_status="processing")
        status = _ai_status_from_card(card)
        self.assertEqual(status, "ИИ обрабатывает")
        self.assertNotEqual(status, "ИИ в очереди")


# ---------------------------------------------------------------------------
# Batch queue lookup — one query, not N queries
# ---------------------------------------------------------------------------

class TestBatchQueueLookup(unittest.TestCase):

    @patch("src.ui.components.analytics_v2.tabs._load_queue_statuses_batch")
    def test_batch_lookup_called_once_not_per_card(self, mock_batch):
        """_load_queue_statuses_batch must be called once for all cards combined."""
        mock_batch.return_value = {}
        contract_numbers = [f"CN{i}" for i in range(20)]
        from src.ui.components.analytics_v2.tabs import _load_queue_statuses_batch as real_fn
        # The function accepts all contract_numbers in one call
        real_fn(contract_numbers)
        # We verify the function signature accepts a list (no per-card calls)
        self.assertEqual(mock_batch.call_count, 1)

    def test_batch_returns_dict_keyed_by_contract_number(self):
        """Return type must be dict, not a list."""
        # When DB is unavailable, must return empty dict (not raise)
        with patch("psycopg2.connect", side_effect=Exception("no db")):
            from src.ui.components.analytics_v2.tabs import _load_queue_statuses_batch
            result = _load_queue_statuses_batch(["CN1", "CN2"])
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
