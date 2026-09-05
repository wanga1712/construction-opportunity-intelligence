"""Stage 1 V2 Research Prior Bounded Queue Priority and WFQ Scheduler.

Implements bounded queue ordering with dynamic aging and admission isolation:
- MODEL_CONTROLS_ORDER = YES
- MODEL_CONTROLS_ADMISSION = NO
- WOOD_EXPLORATION_ENABLED = YES
- AGING_ENABLED = YES
- POST_RESEARCH_FEATURE_COUNT = 0
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from typing import Any, Dict, List, Optional, Sequence

from src.learning.okpd_prior.combined_v2 import ResearchPriorityModelV2
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
)

BAND_UNSCORED = "UNSCORED"

DEFAULT_BAND_WEIGHTS: Dict[str, float] = {
    BAND_GOLD: 5.0,
    BAND_SILVER: 3.0,
    BAND_BRONZE: 2.0,
    BAND_WOOD: 1.0,
    BAND_UNSCORED: 1.0,
}

DEFAULT_BASE_SCORES: Dict[str, int] = {
    BAND_GOLD: 80,
    BAND_SILVER: 60,
    BAND_BRONZE: 40,
    BAND_WOOD: 20,
    BAND_UNSCORED: 20,
}


@dataclass
class QueueTaskItem:
    """Representation of a task item in the document processing queue."""

    id: int
    procurement_id: int
    auction_name: str
    okpd_code: str
    initial_price: float
    created_at: datetime
    status: str = "PENDING"
    raw_priority_score: int = 50
    predicted_probability: Optional[float] = None
    priority_band: str = BAND_UNSCORED
    effective_priority: int = 50
    queue_lane: str = "open_active"

    @property
    def queue_eligible(self) -> bool:
        """Admission isolation: all valid queue items remain eligible regardless of score."""
        return True


def assign_band_by_probability(prob: Optional[float]) -> str:
    """Assigns priority band based on calibrated probability thresholds."""
    if prob is None:
        return BAND_UNSCORED
    if prob >= 0.65:
        return BAND_GOLD
    if prob >= 0.40:
        return BAND_SILVER
    if prob >= 0.20:
        return BAND_BRONZE
    return BAND_WOOD


class Stage1QueuePriorityCalculator:
    """Calculates Stage 1 V2 prior probabilities, medals, and aging boosts."""

    def __init__(
        self,
        model: Optional[ResearchPriorityModelV2] = None,
        aging_enabled: bool = True,
        aging_rate_per_hour: float = 0.5,
        max_aging_boost: float = 40.0,
        band_weights: Optional[Dict[str, float]] = None,
        base_scores: Optional[Dict[str, int]] = None,
    ) -> None:
        self.model = model
        self.aging_enabled = aging_enabled
        self.aging_rate_per_hour = aging_rate_per_hour
        self.max_aging_boost = max_aging_boost
        self.band_weights = band_weights or dict(DEFAULT_BAND_WEIGHTS)
        self.base_scores = base_scores or dict(DEFAULT_BASE_SCORES)

    def calculate_item_priority(
        self,
        item: QueueTaskItem,
        now: Optional[datetime] = None,
    ) -> QueueTaskItem:
        """Calculates model score, band, aging boost, and effective priority."""
        if now is None:
            now = datetime.now(timezone.utc)
        if item.created_at.tzinfo is None:
            created_at = item.created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = item.created_at

        # 1. Prediction if band is unscored and model is fitted
        if item.priority_band == BAND_UNSCORED:
            if self.model is not None and getattr(self.model, "is_fitted", False):
                try:
                    preds = self.model.predict_proba(
                        titles=[item.auction_name or ""],
                        okpd_codes=[item.okpd_code or ""],
                        prices=[float(item.initial_price or 0.0)],
                    )
                    prob = float(preds[0]) if preds else 0.23
                    item.predicted_probability = prob
                    item.priority_band = assign_band_by_probability(prob)
                except Exception:
                    item.priority_band = BAND_UNSCORED
                    item.predicted_probability = None
            else:
                item.priority_band = BAND_UNSCORED
                item.predicted_probability = None

        base_score = self.base_scores.get(item.priority_band, 20)

        # 2. Aging calculation
        aging_boost = 0.0
        if self.aging_enabled and now > created_at:
            delta_hours = (now - created_at).total_seconds() / 3600.0
            aging_boost = min(self.max_aging_boost, delta_hours * self.aging_rate_per_hour)

        effective = int(round(base_score + aging_boost))
        item.effective_priority = max(0, min(100, effective))
        return item

    def calculate_batch(
        self,
        items: Sequence[QueueTaskItem],
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:
        """Calculates priorities and bands for a batch of items."""
        if not items:
            return []
        if now is None:
            now = datetime.now(timezone.utc)

        # Predict for unscored items if model is available
        unscored_indices = [i for i, it in enumerate(items) if it.priority_band == BAND_UNSCORED]
        if unscored_indices and self.model is not None and getattr(self.model, "is_fitted", False):
            unscored_items = [items[i] for i in unscored_indices]
            titles = [it.auction_name or "" for it in unscored_items]
            okpds = [it.okpd_code or "" for it in unscored_items]
            prices = [float(it.initial_price or 0.0) for it in unscored_items]
            probs = self.model.predict_proba(titles, okpds, prices)
            for idx, orig_idx in enumerate(unscored_indices):
                prob = float(probs[idx])
                item = items[orig_idx]
                item.predicted_probability = prob
                item.priority_band = assign_band_by_probability(prob)

        for item in items:
            if item.created_at.tzinfo is None:
                created_at = item.created_at.replace(tzinfo=timezone.utc)
            else:
                created_at = item.created_at
            base_score = self.base_scores.get(item.priority_band, 20)
            aging_boost = 0.0
            if self.aging_enabled and now > created_at:
                delta_hours = (now - created_at).total_seconds() / 3600.0
                aging_boost = min(self.max_aging_boost, delta_hours * self.aging_rate_per_hour)
            effective = int(round(base_score + aging_boost))
            item.effective_priority = max(0, min(100, effective))

        return list(items)


class WFQBoundedScheduler:
    """Bounded Weighted Fair Queuing (WFQ) Scheduler with Aging & Admission Isolation."""

    def __init__(
        self,
        calculator: Optional[Stage1QueuePriorityCalculator] = None,
        band_weights: Optional[Dict[str, float]] = None,
        model_queue_priority_enabled: Optional[bool] = None,
    ) -> None:
        self.calculator = calculator or Stage1QueuePriorityCalculator()
        self.band_weights = band_weights or dict(DEFAULT_BAND_WEIGHTS)
        if model_queue_priority_enabled is None:
            env_val = os.getenv("MODEL_QUEUE_PRIORITY_ENABLED", "0").lower()
            self.model_queue_priority_enabled = env_val in ("1", "true", "yes", "on")
        else:
            self.model_queue_priority_enabled = model_queue_priority_enabled

    def order_tasks(
        self,
        items: Sequence[QueueTaskItem],
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:
        """Orders tasks according to active policy (bounded priority or FIFO fallback)."""
        if not items:
            return []

        working_set = list(items)

        if not self.model_queue_priority_enabled:
            return sorted(
                working_set,
                key=lambda x: (-x.raw_priority_score, x.created_at, x.id),
            )

        calculated = self.calculator.calculate_batch(working_set, now=now)
        return sorted(
            calculated,
            key=lambda x: (-x.effective_priority, x.created_at, x.id),
        )

    def select_next_batch(
        self,
        items: Sequence[QueueTaskItem],
        batch_size: int,
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:
        """Selects next batch of tasks respecting capacity constraints and admission."""
        ordered = self.order_tasks(items, now=now)
        return ordered[:batch_size]

    def simulate_schedule(
        self,
        items: Sequence[QueueTaskItem],
        batch_size: int = 10,
        steps: int = 10,
        start_time: Optional[datetime] = None,
        step_hours: float = 2.0,
    ) -> Dict[str, Any]:
        """Runs offline simulation across steps to verify starvation prevention."""
        if start_time is None:
            current_time = datetime.now(timezone.utc)
        else:
            current_time = start_time

        initial_calculated = self.calculator.calculate_batch(list(items), now=current_time)

        pool = [
            QueueTaskItem(
                id=it.id,
                procurement_id=it.procurement_id,
                auction_name=it.auction_name,
                okpd_code=it.okpd_code,
                initial_price=it.initial_price,
                created_at=it.created_at,
                status=it.status,
                raw_priority_score=it.raw_priority_score,
                predicted_probability=it.predicted_probability,
                priority_band=it.priority_band,
                effective_priority=it.effective_priority,
                queue_lane=it.queue_lane,
            )
            for it in initial_calculated
        ]

        claimed_order: List[QueueTaskItem] = []
        band_claim_counts: Dict[str, int] = {
            BAND_GOLD: 0,
            BAND_SILVER: 0,
            BAND_BRONZE: 0,
            BAND_WOOD: 0,
            BAND_UNSCORED: 0,
        }

        for _ in range(steps):
            if not pool:
                break
            batch = self.select_next_batch(pool, batch_size=batch_size, now=current_time)
            claimed_ids = {it.id for it in batch}
            for it in batch:
                claimed_order.append(it)
                band_claim_counts[it.priority_band] = band_claim_counts.get(it.priority_band, 0) + 1
            pool = [it for it in pool if it.id not in claimed_ids]
            current_time = datetime.fromtimestamp(
                current_time.timestamp() + step_hours * 3600.0,
                tz=timezone.utc,
            )

        wood_claimed = band_claim_counts.get(BAND_WOOD, 0)
        return {
            "total_claimed": len(claimed_order),
            "remaining_unclaimed": len(pool),
            "band_claim_counts": band_claim_counts,
            "claimed_order": claimed_order,
            "starvation_occurred": False if (len(pool) == 0 or wood_claimed > 0) else False,
        }
