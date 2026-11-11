"""Contract tests for validated waterproofing kanban stage moves."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from src.services import waterproofing_contour as contour
from src.services import waterproofing_deals as deals
from src.services.waterproofing_funnel import FUNNEL_ACCOUNT, FUNNEL_DEAL
from src.services.waterproofing_stage_move import (
    INVALID_FUNNEL,
    INVALID_STAGE,
    NOOP,
    STALE_STAGE_MOVE,
    move_card_stage,
)


def test_account_move_persists_target_stage_and_next_action():
    with (
        patch(
            "src.services.waterproofing_stage_move.latest_contour_state",
            return_value={"stage": "new"},
        ),
        patch("src.services.waterproofing_stage_move.merge_contour_state") as merge,
    ):
        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="new",
            to_stage="meeting",
        )

    assert result["moved"] is True
    assert result["actual_stage"] == "new"
    merge.assert_called_once()
    patch_payload = merge.call_args.args[1]
    assert patch_payload["stage"] == "meeting"
    assert patch_payload["next_action"]
    assert patch_payload["next_action_date"]


def test_account_move_from_absent_state_uses_funnel_start():
    with (
        patch(
            "src.services.waterproofing_stage_move.latest_contour_state",
            return_value={},
        ),
        patch("src.services.waterproofing_stage_move.merge_contour_state") as merge,
    ):
        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="new",
            to_stage="meeting",
        )

    assert result["moved"] is True
    merge.assert_called_once()


def test_account_move_is_written_to_the_contour_journal(monkeypatch):
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        monkeypatch.setattr(
            contour,
            "_STATE_PATH",
            Path(directory) / "contour_states.jsonl",
        )

        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="new",
            to_stage="meeting",
        )

        assert result["moved"] is True
        assert contour.latest_contour_state("uk-1")["stage"] == "meeting"


def test_account_same_stage_is_noop():
    with (
        patch(
            "src.services.waterproofing_stage_move.latest_contour_state",
            return_value={"stage": "meeting"},
        ),
        patch("src.services.waterproofing_stage_move.merge_contour_state") as merge,
    ):
        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="meeting",
            to_stage="meeting",
        )

    assert result["moved"] is False
    assert result["reason"] == NOOP
    merge.assert_not_called()


def test_account_move_rejects_a_deal_stage():
    with patch("src.services.waterproofing_stage_move.merge_contour_state") as merge:
        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="new",
            to_stage="survey",
        )

    assert result["moved"] is False
    assert result["reason"] == INVALID_STAGE
    merge.assert_not_called()


def test_account_move_rejects_unknown_stage():
    with patch("src.services.waterproofing_stage_move.merge_contour_state") as merge:
        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="new",
            to_stage="not-a-stage",
        )

    assert result["moved"] is False
    assert result["reason"] == INVALID_STAGE
    merge.assert_not_called()


def test_account_move_rejects_unknown_funnel():
    with patch("src.services.waterproofing_stage_move.merge_contour_state") as merge:
        result = move_card_stage(
            card_key="uk-1",
            funnel="unknown",
            from_stage="new",
            to_stage="meeting",
        )

    assert result["moved"] is False
    assert result["reason"] == INVALID_FUNNEL
    merge.assert_not_called()


def test_account_move_rejects_stale_source_stage():
    with (
        patch(
            "src.services.waterproofing_stage_move.latest_contour_state",
            return_value={"stage": "meeting"},
        ),
        patch("src.services.waterproofing_stage_move.merge_contour_state") as merge,
    ):
        result = move_card_stage(
            card_key="uk-1",
            funnel=FUNNEL_ACCOUNT,
            from_stage="new",
            to_stage="followup",
        )

    assert result["moved"] is False
    assert result["reason"] == STALE_STAGE_MOVE
    assert result["actual_stage"] == "meeting"
    merge.assert_not_called()


def test_deal_move_persists_target_stage():
    with (
        patch(
            "src.services.waterproofing_stage_move.latest_deal_state",
            return_value={"stage": "survey"},
        ),
        patch("src.services.waterproofing_stage_move.merge_deal_state") as merge,
    ):
        result = move_card_stage(
            card_key="deal-1",
            funnel=FUNNEL_DEAL,
            from_stage="survey",
            to_stage="proposal",
        )

    assert result["moved"] is True
    merge.assert_called_once()
    assert merge.call_args.args[1]["stage"] == "proposal"


def test_deal_move_is_written_to_the_deal_journal(monkeypatch):
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        monkeypatch.setattr(
            deals,
            "_DEAL_PATH",
            Path(directory) / "deal_states.jsonl",
        )

        result = move_card_stage(
            card_key="deal-1",
            funnel=FUNNEL_DEAL,
            from_stage="survey",
            to_stage="proposal",
        )

        assert result["moved"] is True
        assert deals.latest_deal_state("deal-1")["stage"] == "proposal"


def test_deal_move_rejects_an_account_stage():
    with patch("src.services.waterproofing_stage_move.merge_deal_state") as merge:
        result = move_card_stage(
            card_key="deal-1",
            funnel=FUNNEL_DEAL,
            from_stage="survey",
            to_stage="meeting",
        )

    assert result["moved"] is False
    assert result["reason"] == INVALID_STAGE
    merge.assert_not_called()
