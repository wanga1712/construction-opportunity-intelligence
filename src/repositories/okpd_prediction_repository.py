"""Repository for reading and querying shadow OKPD research priority predictions."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from src.learning.okpd_prior.dto import ShadowPredictionDTO
from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.learning.okpd_prior.model import (
    BAND_WOOD,
    OKPDResearchHitModelV1,
    assign_priority_band,
)

logger = logging.getLogger("crm.repositories.okpd_prediction_repository")

_GLOBAL_MODEL_INSTANCE: Optional[OKPDResearchHitModelV1] = None


def get_default_model() -> OKPDResearchHitModelV1:
    """Returns singleton model instance, fitted on baseline rules if uninitialized."""
    global _GLOBAL_MODEL_INSTANCE
    if _GLOBAL_MODEL_INSTANCE is None:
        _GLOBAL_MODEL_INSTANCE = OKPDResearchHitModelV1()
        # Initialize with standard construction OKPD priors
        from src.learning.okpd_prior.dataset import ProcurementDatasetRow
        # Default construction priors if no artifact loaded yet
        _GLOBAL_MODEL_INSTANCE.fit([])
    return _GLOBAL_MODEL_INSTANCE


def set_default_model(model: OKPDResearchHitModelV1) -> None:
    """Sets active singleton model instance."""
    global _GLOBAL_MODEL_INSTANCE
    _GLOBAL_MODEL_INSTANCE = model


class OKPDPriorPredictionRepository:
    """Safe read-only repository for OKPD research priority predictions."""

    def __init__(
        self,
        in_memory_predictions: Optional[Dict[int, ShadowPredictionDTO]] = None,
        fallback_to_model: bool = True,
    ) -> None:
        self._in_memory: Dict[int, ShadowPredictionDTO] = dict(in_memory_predictions or {})
        self._fallback_to_model = fallback_to_model

    def store_prediction(self, pred: ShadowPredictionDTO) -> None:
        """Stores a prediction in memory."""
        self._in_memory[pred.procurement_id] = pred

    def get_by_procurement_id(
        self,
        procurement_id: int,
        okpd_code: Optional[str] = None,
    ) -> Optional[ShadowPredictionDTO]:
        """Retrieves prediction for a single procurement, with fallback calculation."""
        if procurement_id in self._in_memory:
            return self._in_memory[procurement_id]

        if not self._fallback_to_model or okpd_code is None:
            return None

        # Compute shadow prediction on the fly
        model = get_default_model()
        h = parse_okpd_hierarchy(okpd_code)
        p = model.predict_proba_single(h)
        # For single on-the-fly lookup, estimate percentile from prior
        percentile = min(1.0, max(0.0, p * 4.0))  # Scale ~0.25 to 1.0
        band = assign_priority_band(percentile)

        from datetime import datetime, timezone
        return ShadowPredictionDTO(
            procurement_id=procurement_id,
            model_name=model.model_name,
            model_version=model.model_version,
            trained_at=model.trained_at,
            dataset_snapshot_sha256=model.dataset_snapshot_sha256,
            p_research_hit=p,
            priority_percentile=percentile,
            priority_band=band,
            okpd_code_raw=okpd_code,
            okpd_root=h.okpd_root,
            okpd_level2=h.okpd_level2,
            okpd_level3=h.okpd_level3,
            okpd_full=h.okpd_full,
            prediction_created_at=datetime.now(timezone.utc).isoformat(),
            shadow_only=True,
        )

    def get_batch(
        self,
        procurements: Sequence[Dict[str, Any]],
    ) -> Dict[int, ShadowPredictionDTO]:
        """Returns predictions for a batch of procurement dicts (id, okpd_code)."""
        result: Dict[int, ShadowPredictionDTO] = {}
        missing = []
        for p in procurements:
            pid = p.get("id") or p.get("procurement_id")
            if pid in self._in_memory:
                result[pid] = self._in_memory[pid]
            else:
                missing.append(p)

        if missing and self._fallback_to_model:
            model = get_default_model()
            scored = model.score_population(missing)
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            for s in scored:
                dto = ShadowPredictionDTO(
                    procurement_id=s.procurement_id,
                    model_name=model.model_name,
                    model_version=model.model_version,
                    trained_at=model.trained_at,
                    dataset_snapshot_sha256=model.dataset_snapshot_sha256,
                    p_research_hit=s.p_research_hit,
                    priority_percentile=s.priority_percentile,
                    priority_band=s.priority_band,
                    okpd_code_raw=s.okpd_code_raw,
                    okpd_root=s.okpd_root,
                    okpd_level2=s.okpd_level2,
                    okpd_level3=s.okpd_level3,
                    okpd_full=s.okpd_full,
                    prediction_created_at=now_iso,
                    shadow_only=True,
                )
                result[s.procurement_id] = dto

        return result
