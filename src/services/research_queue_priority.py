"""Stage 1 V2 Research Prior Bounded Queue Priority and DWRR Scheduler.

Implements real Deficit Weighted Round Robin (DWRR) queue scheduling with dynamic aging
and admission isolation:
- MODEL_CONTROLS_ORDER = YES
- MODEL_CONTROLS_ADMISSION = NO
- WOOD_EXPLORATION_ENABLED = YES
- AGING_ENABLED = YES
- POST_RESEARCH_FEATURE_COUNT = 0
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.learning.okpd_prior.combined_v2 import ResearchPriorityModelV2
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    assign_priority_band,
)

BAND_UNSCORED = "UNSCORED"
ALL_BANDS: Tuple[str, ...] = (BAND_GOLD, BAND_SILVER, BAND_BRONZE, BAND_WOOD, BAND_UNSCORED)

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
    priority_percentile: Optional[float] = None
    priority_band: str = BAND_UNSCORED
    effective_priority: int = 50
    queue_lane: str = "open_active"

    @property
    def queue_eligible(self) -> bool:
        """Admission isolation: all valid queue items remain eligible regardless of score."""
        return True


def load_production_model(model_dir: Optional[str] = None) -> Optional[ResearchPriorityModelV2]:
    """Loads production ResearchPriorityModelV2 from manifest and artifact."""
    if model_dir is None:
        candidates = [
            Path("data/models/research_priority_v2"),
            Path("/opt/CRM_Streamlit/data/models/research_priority_v2"),
            Path("/opt/tender_documents_research/data/models/research_priority_v2"),
        ]
        target_dir = None
        for c in candidates:
            if c.exists() and (c / "manifest.json").exists():
                target_dir = c
                break
        if target_dir is None:
            return None
    else:
        target_dir = Path(model_dir)

    manifest_file = target_dir / "manifest.json"
    if not manifest_file.exists():
        return None

    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        pkl_file = target_dir / manifest.get("artifact_filename", "")
        if not pkl_file.exists():
            return None
        return ResearchPriorityModelV2.load_artifact(str(pkl_file))
    except Exception:
        return None


class Stage1QueuePriorityCalculator:
    """Calculates Stage 1 V2 prior probabilities, canonical percentiles, medals, and aging."""

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
        """Calculates prior, band, and effective priority for a single item."""
        res = self.calculate_population([item], now=now)
        return res[0]

    def calculate_population(
        self,
        items: Sequence[QueueTaskItem],
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:

        """Scores a population of items with canonical MAX_RANK percentiles and medals."""
        if not items:
            return []
        if now is None:
            now = datetime.now(timezone.utc)

        working = list(items)
        need_scoring = [
            it for it in working
            if it.priority_band not in (BAND_GOLD, BAND_SILVER, BAND_BRONZE, BAND_WOOD)
        ]
        if need_scoring and self.model is not None and getattr(self.model, "is_fitted", False):
            titles = [it.auction_name or "" for it in need_scoring]
            okpds = [it.okpd_code or "" for it in need_scoring]
            prices = [float(it.initial_price or 0.0) for it in need_scoring]
            probs = self.model.predict_proba(titles, okpds, prices)
            n = len(probs)
            sorted_probs = np.sort(probs)
            for idx, item in enumerate(need_scoring):
                prob = float(probs[idx])
                item.predicted_probability = prob
                # Canonical MAX_RANK percentile
                count_le = int(np.searchsorted(sorted_probs, prob, side="right"))
                percentile = round(count_le / float(n), 4)
                item.priority_percentile = percentile
                item.priority_band = assign_priority_band(percentile)
        elif need_scoring:
            for item in need_scoring:
                item.predicted_probability = None
                item.priority_percentile = None
                item.priority_band = BAND_UNSCORED


        for item in working:
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

        return working


class WFQBoundedScheduler:
    """Real Deficit Weighted Round Robin (DWRR) Bounded Queue Scheduler."""

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

    def schedule_dwrr(
        self,
        items: Sequence[QueueTaskItem],
        limit: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:
        """Selects items using Deficit Weighted Round Robin across priority bands."""
        if not items:
            return []

        # 1. Score items if needed
        scored_items = self.calculator.calculate_population(items, now=now)

        # 2. Group items by band and sort within band by effective_priority DESC, created_at ASC, id ASC
        band_queues: Dict[str, List[QueueTaskItem]] = {b: [] for b in ALL_BANDS}
        for item in scored_items:
            band = item.priority_band if item.priority_band in band_queues else BAND_UNSCORED
            band_queues[band].append(item)

        for b in ALL_BANDS:
            band_queues[b].sort(key=lambda x: (-x.effective_priority, x.created_at, x.id))

        target_count = len(scored_items) if limit is None else min(limit, len(scored_items))
        scheduled: List[QueueTaskItem] = []
        deficits: Dict[str, float] = {b: 0.0 for b in ALL_BANDS}

        # 3. DWRR iteration
        max_loops = target_count * 10 + 100
        loops = 0
        while len(scheduled) < target_count and loops < max_loops:
            loops += 1
            active_any = False
            for band in ALL_BANDS:
                q = band_queues[band]
                if not q:
                    deficits[band] = 0.0
                    continue
                active_any = True
                deficits[band] += self.band_weights.get(band, 1.0)
                while deficits[band] >= 1.0 and q and len(scheduled) < target_count:
                    item = q.pop(0)
                    scheduled.append(item)
                    deficits[band] -= 1.0
            if not active_any:
                break

        return scheduled

    def order_tasks(
        self,
        items: Sequence[QueueTaskItem],
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:
        """Orders tasks according to active policy (DWRR bounded scheduler or FIFO fallback)."""
        if not items:
            return []

        working_set = list(items)
        if not self.model_queue_priority_enabled:
            return sorted(
                working_set,
                key=lambda x: (-x.raw_priority_score, x.created_at, x.id),
            )

        return self.schedule_dwrr(working_set, limit=len(working_set), now=now)

    def select_next_batch(
        self,
        items: Sequence[QueueTaskItem],
        batch_size: int,
        now: Optional[datetime] = None,
    ) -> List[QueueTaskItem]:
        """Selects next batch of tasks respecting bounded weights and admission."""
        if not self.model_queue_priority_enabled:
            ordered = self.order_tasks(items, now=now)
            return ordered[:batch_size]
        return self.schedule_dwrr(items, limit=batch_size, now=now)

    def simulate_schedule(
        self,
        items: Sequence[QueueTaskItem],
        batch_size: int = 10,
        steps: int = 10,
        start_time: Optional[datetime] = None,
        step_hours: float = 2.0,
    ) -> Dict[str, Any]:
        """Runs offline simulation across steps and checks starvation."""
        if start_time is None:
            current_time = datetime.now(timezone.utc)
        else:
            current_time = start_time

        initial_calculated = self.calculator.calculate_population(list(items), now=current_time)

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
                priority_percentile=it.priority_percentile,
                priority_band=it.priority_band,
                effective_priority=it.effective_priority,
                queue_lane=it.queue_lane,
            )
            for it in initial_calculated
        ]

        claimed_order: List[QueueTaskItem] = []
        band_claim_counts: Dict[str, int] = {b: 0 for b in ALL_BANDS}
        starvation_detected = False

        wood_in_pool = sum(1 for it in pool if it.priority_band == BAND_WOOD)

        for step in range(steps):
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

        # Starvation is detected if WOOD existed in initial pool with enough steps/capacity but received 0 claims
        if wood_in_pool > 0 and len(claimed_order) >= 15 and band_claim_counts.get(BAND_WOOD, 0) == 0:
            starvation_detected = True

        return {
            "total_claimed": len(claimed_order),
            "remaining_unclaimed": len(pool),
            "band_claim_counts": band_claim_counts,
            "claimed_order": claimed_order,
            "starvation_detected": starvation_detected,
            "starvation_occurred": starvation_detected,
        }

