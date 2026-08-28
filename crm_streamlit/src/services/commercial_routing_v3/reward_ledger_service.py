"""Centralized reward ledger service.

Manages reward weights and writes immutable feedback events on human/model corrections.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("commercial_routing_v3.reward_ledger_service")

REWARD_CONFIG_VERSION = "REWARD_CONFIG_V1"

REWARD_MAP = {
    "HUMAN_CONFIRM_CATEGORY": 3.0,
    "HUMAN_CONFIRM_PRODUCT": 3.0,
    "HUMAN_CONFIRM_MEDAL": 2.0,
    "HUMAN_CONFIRM_OBJECT": 2.0,
    
    "AUDITOR_CAUGHT_FALSE_POSITIVE": 3.0,
    "AUDITOR_FOUND_MISSED_CATEGORY": 3.0,
    
    "HUMAN_CORRECT_CATEGORY": -3.0,
    "HUMAN_CORRECT_PRODUCT": -3.0,
    "HUMAN_CORRECT_OBJECT": -2.0,
    "HUMAN_CORRECT_MODE": -2.0,
    
    "FALSE_GOLD": -4.0,
    "FALSE_IN_CATEGORY": -4.0,
    "MISSED_CONFIRMED_CATEGORY": -4.0,
    "MISSED_CONFIRMED_PRODUCT": -4.0,
    
    "BOTH_MODELS_SAME_WRONG": -5.0,
}

class RewardLedgerService:
    """Centralized service for recording reward points and audit trails."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def write_reward_event(
        self,
        *,
        procurement_id: int,
        field: str,
        event_type: str,
        hunter_run_id: Optional[int] = None,
        auditor_run_id: Optional[int] = None,
        old_model_value: Optional[str] = None,
        auditor_value: Optional[str] = None,
        human_value: Optional[str] = None,
    ) -> Optional[int]:
        """Write one reward event log to crm_v3_reward_ledger."""
        reward = REWARD_MAP.get(event_type, 0.0)
        
        rows = self.crm_db.execute_query(
            """
            INSERT INTO crm_v3_reward_ledger (
                procurement_id, field, event_type, hunter_run_id,
                auditor_run_id, old_model_value, auditor_value,
                human_value, reward_config_version, reward
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                procurement_id,
                field,
                event_type,
                hunter_run_id,
                auditor_run_id,
                old_model_value,
                auditor_value,
                human_value,
                REWARD_CONFIG_VERSION,
                reward,
            ),
        )
        if rows:
            row = rows[0]
            event_id = int(row["id"] if isinstance(row, dict) else row[0])
            logger.info(
                f"[RewardLedger] Event written: id={event_id} type={event_type} reward={reward} proc={procurement_id}"
            )
            return event_id
        return None

    def record_feedback_rewards(self, procurement_id: int, payload: dict) -> None:
        """Analyze human feedback/annotation payload and record rewards/penalties."""
        if not hasattr(self.crm_db, "execute_query"):
            logger.warning("[RewardLedger] crm_db does not support execute_query; skipping feedback rewards (likely mock in tests).")
            return
        traces = self.crm_db.execute_query(
            """
            SELECT hunter_run_id, auditor_run_id 
            FROM crm_v3_autonomous_analysis_traces 
            WHERE procurement_id = %s 
            ORDER BY id DESC LIMIT 1
            """,
            (procurement_id,)
        )
        if not traces:
            return
        trace = traces[0]
        hunter_run_id = trace.get("hunter_run_id")
        auditor_run_id = trace.get("auditor_run_id")
        
        hunter_result = {}
        if hunter_run_id:
            hr = self.crm_db.execute_query(
                "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
                (hunter_run_id,)
            )
            if hr:
                hunter_result = hr[0].get("validated_model_result") or {}
                
        auditor_result = {}
        if auditor_run_id:
            ar = self.crm_db.execute_query(
                "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
                (auditor_run_id,)
            )
            if ar:
                auditor_result = ar[0].get("validated_model_result") or {}

        # 1. Object Type Confirm/Correct
        expert_obj = payload.get("object_type")
        model_obj = hunter_result.get("object_type")
        if expert_obj and model_obj:
            if expert_obj == model_obj:
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="object_type",
                    event_type="HUMAN_CONFIRM_OBJECT",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=model_obj,
                    human_value=expert_obj,
                )
            else:
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="object_type",
                    event_type="HUMAN_CORRECT_OBJECT",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=model_obj,
                    human_value=expert_obj,
                )

        # 2. Procurement Mode Confirm/Correct
        expert_mode = payload.get("procurement_mode")
        model_mode = hunter_result.get("procurement_mode")
        if expert_mode and model_mode:
            if expert_mode != model_mode:
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="procurement_mode",
                    event_type="HUMAN_CORRECT_MODE",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=model_mode,
                    human_value=expert_mode,
                )

        # 3. Categories & Products Confirm/Correct
        expert_cats = set(payload.get("category_codes") or [])
        model_cats = set(hunter_result.get("categories") or [])
        
        # Auditor discovered missed category candidates
        auditor_missed_candidates = auditor_result.get("auditor_discovered_candidate") or []
        auditor_missed_codes = {c.get("category_code") for c in auditor_missed_candidates if c.get("category_code")}

        # Confirmed categories
        for cat in expert_cats:
            if cat in model_cats:
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="category",
                    event_type="HUMAN_CONFIRM_CATEGORY",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=cat,
                    human_value=cat,
                )
                # Human confirmed a product in this category
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="product",
                    event_type="HUMAN_CONFIRM_PRODUCT",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=cat,
                    human_value=cat,
                )
            else:
                # Expert confirmed category that Hunter missed.
                # Check if Auditor caught it:
                if cat in auditor_missed_codes:
                    self.write_reward_event(
                        procurement_id=procurement_id,
                        field="category",
                        event_type="AUDITOR_FOUND_MISSED_CATEGORY",
                        hunter_run_id=hunter_run_id,
                        auditor_run_id=auditor_run_id,
                        old_model_value=None,
                        auditor_value=cat,
                        human_value=cat,
                    )
                else:
                    # Both models missed it!
                    self.write_reward_event(
                        procurement_id=procurement_id,
                        field="category",
                        event_type="MISSED_CONFIRMED_CATEGORY",
                        hunter_run_id=hunter_run_id,
                        auditor_run_id=auditor_run_id,
                        old_model_value=None,
                        human_value=cat,
                    )
                    self.write_reward_event(
                        procurement_id=procurement_id,
                        field="product",
                        event_type="MISSED_CONFIRMED_PRODUCT",
                        hunter_run_id=hunter_run_id,
                        auditor_run_id=auditor_run_id,
                        old_model_value=None,
                        human_value=cat,
                    )

        # Rejected (false positive) categories
        for cat in model_cats:
            if cat not in expert_cats:
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="category",
                    event_type="HUMAN_CORRECT_CATEGORY",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=cat,
                    human_value=None,
                )
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="product",
                    event_type="HUMAN_CORRECT_PRODUCT",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=cat,
                    human_value=None,
                )
                
                # Check if Auditor caught the false positive (disagreed on this category)
                auditor_cats_verdicts = auditor_result.get("categories") or []
                auditor_disagreed = any(
                    cv.get("category_code") == cat and cv.get("verdict") == "DISAGREE"
                    for cv in auditor_cats_verdicts
                )
                if auditor_disagreed:
                    self.write_reward_event(
                        procurement_id=procurement_id,
                        field="category",
                        event_type="AUDITOR_CAUGHT_FALSE_POSITIVE",
                        hunter_run_id=hunter_run_id,
                        auditor_run_id=auditor_run_id,
                        old_model_value=cat,
                        auditor_value="DISAGREE",
                        human_value=None,
                    )
                else:
                    # Both models failed (Hunter predicted category and Auditor agreed, but human rejected)
                    self.write_reward_event(
                        procurement_id=procurement_id,
                        field="category",
                        event_type="BOTH_MODELS_SAME_WRONG",
                        hunter_run_id=hunter_run_id,
                        auditor_run_id=auditor_run_id,
                        old_model_value=cat,
                        auditor_value="AGREE",
                        human_value=None,
                    )

        # 4. Commercial Entry & Medal Confirm/Correct
        expert_medal = payload.get("expert_medal")
        model_medal = hunter_result.get("medal_hypothesis")
        expert_comm = payload.get("commercial_entry")
        model_comm = hunter_result.get("commercial_entry")

        if expert_medal and model_medal:
            if expert_medal == model_medal:
                self.write_reward_event(
                    procurement_id=procurement_id,
                    field="medal",
                    event_type="HUMAN_CONFIRM_MEDAL",
                    hunter_run_id=hunter_run_id,
                    auditor_run_id=auditor_run_id,
                    old_model_value=model_medal,
                    human_value=expert_medal,
                )
            else:
                # False Gold penalty
                if model_medal == "GOLD" and expert_medal in ("WOOD", "NON_COMMERCIAL"):
                    self.write_reward_event(
                        procurement_id=procurement_id,
                        field="medal",
                        event_type="FALSE_GOLD",
                        hunter_run_id=hunter_run_id,
                        auditor_run_id=auditor_run_id,
                        old_model_value=model_medal,
                        human_value=expert_medal,
                    )

        if expert_comm == "NON_COMMERCIAL" and model_comm == "COMMERCIAL":
            self.write_reward_event(
                procurement_id=procurement_id,
                field="commercial_entry",
                event_type="FALSE_IN_CATEGORY",
                hunter_run_id=hunter_run_id,
                auditor_run_id=auditor_run_id,
                old_model_value=model_comm,
                human_value=expert_comm,
            )
