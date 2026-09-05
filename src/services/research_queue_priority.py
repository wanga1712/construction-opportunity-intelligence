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


class DWRRBoundedScheduler:
    """Weighted Virtual Time (Stride) Bounded Queue Scheduler.

    Algorithm: each band has a persistent virtual clock. On each selection,
    the band with the LOWEST virtual time is served and its clock advances
    by ``1/weight``. Higher-weight bands advance more slowly and therefore
    receive proportionally more service.

    This is a Stride / Weighted Virtual Time scheduler, not classical
    Deficit Weighted Round Robin. The class name ``DWRRBoundedScheduler``
    and alias ``WFQBoundedScheduler`` are retained for backward
    compatibility only.

    Weights: GOLD=5, SILVER=3, BRONZE=2, WOOD=1, UNSCORED=1.
    Expected long-run shares: GOLD ≈45.5%, SILVER ≈27.3%,
    BRONZE ≈18.2%, WOOD ≈9.1%.
    """

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
        # Persistent DWRR state — survives across sequential claim calls
        self._deficits: Dict[str, float] = {b: 0.0 for b in ALL_BANDS}
        self._band_cursor: int = 0  # rotation cursor for fair band scanning
        # Observability counters — lifetime claim counts per band
        self._claim_counters: Dict[str, int] = {b: 0 for b in ALL_BANDS}

    def get_counters(self) -> Dict[str, int]:
        """Return lifetime DWRR claim counters per band."""
        return dict(self._claim_counters)

    def reset_counters(self) -> None:
        """Reset lifetime claim counters."""
        self._claim_counters = {b: 0 for b in ALL_BANDS}

    def get_deficits(self) -> Dict[str, float]:
        """Return current DWRR deficit state (for testing/diagnostics)."""
        return dict(self._deficits)

    def _run_dwrr(
        self,
        band_queues: Dict[str, List[QueueTaskItem]],
        target_count: int,
    ) -> List[QueueTaskItem]:
        """Core Weighted Virtual Time (Stride) scheduling loop.

        Each band has a virtual clock (stored in self._deficits as virtual time).
        When an item is served from a band, its virtual clock advances by 1/weight.
        The band with the LOWEST virtual time (most "deserving") goes next.

        Produces exact weighted ratios and is trivially stateful across calls
        since virtual times persist on the instance.
        """
        scheduled: List[QueueTaskItem] = []
        max_loops = target_count + 100

        for _ in range(max_loops):
            if len(scheduled) >= target_count:
                break

            # Find the active band with the lowest virtual time
            best_band = None
            best_vtime = float("inf")
            for b in ALL_BANDS:
                if not band_queues.get(b):
                    continue
                if self._deficits[b] < best_vtime:
                    best_vtime = self._deficits[b]
                    best_band = b

            if best_band is None:
                break  # all queues empty

            # Serve one item from this band
            item = band_queues[best_band].pop(0)
            scheduled.append(item)
            # Advance virtual time by 1/weight (higher weight = smaller step = more service)
            weight = self.band_weights.get(best_band, 1.0)
            self._deficits[best_band] += 1.0 / weight
            self._claim_counters[best_band] = self._claim_counters.get(best_band, 0) + 1

        return scheduled

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
        return self._run_dwrr(band_queues, target_count)

def get_effective_service_band(row: Dict[str, Any]) -> str:
    """Determine effective service band for DWRR queue scheduling.

    Rule: DIRECT_GOODS_PRIORITY_OVERRIDE
    IF procurement_scope_type = DIRECT_GOODS AND normalized_nmck_rub >= 50_000
    THEN effective_service_band = GOLD
    Otherwise, use normal research_prior_band.
    """
    raw_band = row.get("research_prior_band") or BAND_UNSCORED
    scope_type = row.get("procurement_scope_type") or row.get("scope_type")
    nmck = row.get("normalized_nmck_rub") or row.get("nmck_rub") or row.get("nmck") or 0.0
    try:
        nmck_val = float(nmck)
    except (ValueError, TypeError):
        nmck_val = 0.0

    if scope_type == "DIRECT_GOODS" and nmck_val >= 50000.0:
        return BAND_GOLD
    return raw_band


    def select_from_candidates(
        self,
        candidates: Sequence[Dict[str, Any]],
        batch_size: int,
    ) -> List[int]:
        """Select IDs from pre-locked DB candidate rows using stateful DWRR.

        This is the production entry point. Candidates are dicts with keys:
        id, research_prior_band, research_prior_score, research_prior_effective_score.

        Returns list of selected IDs (up to batch_size).
        """
        if not candidates or batch_size <= 0:
            return []

        # Map DB rows to band queues directly using effective service band
        band_queues: Dict[str, List[Dict[str, Any]]] = {b: [] for b in ALL_BANDS}
        for row in candidates:
            band = get_effective_service_band(row)
            if band not in band_queues:
                band = BAND_UNSCORED
            band_queues[band].append(row)

        # Sort within band: effective_score DESC, research_prior_score DESC, id ASC
        for b in ALL_BANDS:
            band_queues[b].sort(
                key=lambda r: (
                    -(r.get("research_prior_effective_score") or 0),
                    -(r.get("research_prior_score") or 0),
                    r.get("id", 0),
                ),
            )

        # DWRR selection using virtual time (same algorithm as _run_dwrr)
        selected_ids: List[int] = []
        max_loops = batch_size + 100

        for _ in range(max_loops):
            if len(selected_ids) >= batch_size:
                break

            # Find the active band with the lowest virtual time
            best_band = None
            best_vtime = float("inf")
            for b in ALL_BANDS:
                if not band_queues.get(b):
                    continue
                if self._deficits[b] < best_vtime:
                    best_vtime = self._deficits[b]
                    best_band = b

            if best_band is None:
                break  # all queues empty

            # Serve one item from this band
            row = band_queues[best_band].pop(0)
            selected_ids.append(row["id"])
            weight = self.band_weights.get(best_band, 1.0)
            self._deficits[best_band] += 1.0 / weight
            self._claim_counters[best_band] = self._claim_counters.get(best_band, 0) + 1

        return selected_ids

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


# Backward compatibility alias
WFQBoundedScheduler = DWRRBoundedScheduler

