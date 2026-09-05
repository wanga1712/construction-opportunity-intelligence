"""Shared Weighted Claim Policy for production queue repositories.

Provides a single stateful DWRRBoundedScheduler instance (which internally
uses a Weighted Virtual Time / Stride algorithm, not classical DWRR — the
class name is retained for backward compatibility) that both
src/services/queue_repository.py and
tender_documents_research/.../backends/queue_repository.py
use for claim selection.

The scheduler state (virtual time per band) persists for the lifetime of
the DWRRClaimPolicy instance, ensuring bounded weighted service even
across sequential batch_size=1 claims.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

from src.services.research_queue_priority import (
    ALL_BANDS,
    BAND_UNSCORED,
    DEFAULT_BAND_WEIGHTS,
    DWRRBoundedScheduler,
    Stage1QueuePriorityCalculator,
)

logger = logging.getLogger(__name__)

# Pool multiplier: how many candidates to lock relative to batch_size.
# Must be large enough to include items from multiple bands.
POOL_MULTIPLIER = 5
POOL_MIN = 50


def pool_size(batch_size: int) -> int:
    """Calculate candidate pool size for a given batch_size."""
    return max(batch_size * POOL_MULTIPLIER, POOL_MIN)


class DWRRClaimPolicy:
    """Stateful DWRR claim policy shared across production queue repositories.

    Wraps a DWRRBoundedScheduler with persistent deficit state and
    provides a simple interface for two-phase claim selection.
    """

    def __init__(
        self,
        band_weights: Optional[Dict[str, float]] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if enabled is None:
            env_val = os.getenv("MODEL_QUEUE_PRIORITY_ENABLED", "0").lower()
            self._enabled = env_val in ("1", "true", "yes", "on")
        else:
            self._enabled = enabled
        self._scheduler = DWRRBoundedScheduler(
            calculator=Stage1QueuePriorityCalculator(model=None),
            band_weights=band_weights or dict(DEFAULT_BAND_WEIGHTS),
            model_queue_priority_enabled=self._enabled,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def select_from_pool(
        self,
        candidates: Sequence[Dict[str, Any]],
        batch_size: int,
    ) -> List[int]:
        """Run stateful DWRR on pre-locked candidate rows.

        Args:
            candidates: Dicts with at least {id, research_prior_band,
                        research_prior_score, research_prior_effective_score}.
            batch_size: Number of items to select.

        Returns:
            List of selected IDs (up to batch_size).
        """
        selected = self._scheduler.select_from_candidates(candidates, batch_size)
        if selected:
            counters = self._scheduler.get_counters()
            band_this = _count_bands(candidates, selected)
            logger.info(
                "DWRR claim: selected %d/%d | this_batch=%s | lifetime=%s",
                len(selected),
                len(candidates),
                band_this,
                counters,
            )
        return selected

    def get_counters(self) -> Dict[str, int]:
        """Lifetime DWRR claim counters per band."""
        return self._scheduler.get_counters()

    def get_deficits(self) -> Dict[str, float]:
        """Current deficit state (diagnostics)."""
        return self._scheduler.get_deficits()

    def reset_counters(self) -> None:
        self._scheduler.reset_counters()


def _count_bands(
    candidates: Sequence[Dict[str, Any]],
    selected_ids: Sequence[int],
) -> Dict[str, int]:
    """Count bands of selected IDs from candidate dicts."""
    id_to_band = {r["id"]: (r.get("research_prior_band") or BAND_UNSCORED) for r in candidates}
    counts: Dict[str, int] = {}
    for sid in selected_ids:
        band = id_to_band.get(sid, BAND_UNSCORED)
        counts[band] = counts.get(band, 0) + 1
    return counts
