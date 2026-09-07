"""Dependency-light weighted claim policy for the document worker."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

BAND_GOLD = "GOLD"
BAND_SILVER = "SILVER"
BAND_BRONZE = "BRONZE"
BAND_WOOD = "WOOD"
BAND_UNSCORED = "UNSCORED"
ALL_BANDS = (BAND_GOLD, BAND_SILVER, BAND_BRONZE, BAND_WOOD, BAND_UNSCORED)
DEFAULT_BAND_WEIGHTS = {
    BAND_GOLD: 5.0,
    BAND_SILVER: 3.0,
    BAND_BRONZE: 2.0,
    BAND_WOOD: 1.0,
    BAND_UNSCORED: 1.0,
}
POOL_MULTIPLIER = 5
POOL_MIN = 50


def pool_size(batch_size: int) -> int:
    return max(batch_size * POOL_MULTIPLIER, POOL_MIN)


def get_effective_service_band(row: Dict[str, Any]) -> str:
    """Apply the service-band overlay after business admission."""
    raw_band = row.get("research_prior_band") or BAND_UNSCORED
    scope_type = row.get("procurement_scope_type") or row.get("scope_type")
    nmck = row.get("normalized_nmck_rub") or row.get("nmck_rub") or row.get("nmck") or 0.0
    try:
        nmck_value = float(nmck)
    except (TypeError, ValueError):
        nmck_value = 0.0
    if scope_type == "DIRECT_GOODS" and nmck_value >= 50000.0:
        return BAND_GOLD
    return raw_band


class DWRRClaimPolicy:
    """Stateful weighted virtual-time selector for already admitted rows."""

    def __init__(
        self,
        band_weights: Optional[Dict[str, float]] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if enabled is None:
            enabled = os.getenv("MODEL_QUEUE_PRIORITY_ENABLED", "0").lower() in {
                "1", "true", "yes", "on"
            }
        self._enabled = enabled
        self._weights = band_weights or dict(DEFAULT_BAND_WEIGHTS)
        self._deficits = {band: 0.0 for band in ALL_BANDS}
        self._claim_counters = {band: 0 for band in ALL_BANDS}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def select_from_pool(
        self,
        candidates: Sequence[Dict[str, Any]],
        batch_size: int,
    ) -> List[int]:
        if not candidates or batch_size <= 0:
            return []

        seen_ids: set[Any] = set()
        band_queues: Dict[str, List[Dict[str, Any]]] = {band: [] for band in ALL_BANDS}
        for row in candidates:
            row_id = row.get("id")
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            band = get_effective_service_band(row)
            band_queues[band if band in band_queues else BAND_UNSCORED].append(row)

        for rows in band_queues.values():
            rows.sort(
                key=lambda row: (
                    -(row.get("research_prior_effective_score") or 0),
                    -(row.get("research_prior_score") or 0),
                    row.get("id", 0),
                )
            )

        selected: List[int] = []
        for _ in range(batch_size + 100):
            if len(selected) >= batch_size:
                break
            active = [band for band in ALL_BANDS if band_queues[band]]
            if not active:
                break
            band = min(active, key=lambda item: self._deficits[item])
            row = band_queues[band].pop(0)
            selected.append(row["id"])
            self._deficits[band] += 1.0 / self._weights.get(band, 1.0)
            self._claim_counters[band] += 1
        return selected

    def get_counters(self) -> Dict[str, int]:
        return dict(self._claim_counters)

    def get_deficits(self) -> Dict[str, float]:
        return dict(self._deficits)

    def reset_counters(self) -> None:
        self._claim_counters = {band: 0 for band in ALL_BANDS}
