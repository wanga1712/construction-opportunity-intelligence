"""Offline scoring service for TARGET procurements population."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

from src.learning.okpd_prior.dto import ShadowPredictionDTO
from src.learning.okpd_prior.hierarchy import parse_okpd_hierarchy
from src.learning.okpd_prior.model import (
    BAND_BRONZE,
    BAND_GOLD,
    BAND_SILVER,
    BAND_WOOD,
    OKPDResearchHitModelV1,
)

logger = logging.getLogger("crm.learning.okpd_prior.scoring")


def score_procurements_batch(
    model: OKPDResearchHitModelV1,
    procurements: Sequence[Dict[str, Any]],
    output_path: Optional[str] = None,
) -> Tuple[List[ShadowPredictionDTO], Dict[str, Any]]:
    """Scores a batch of procurements and outputs shadow predictions and manifest.

    Args:
        model: Fitted OKPDResearchHitModelV1 instance.
        procurements: List of dicts with 'id' (or 'procurement_id') and 'okpd_code'.
        output_path: Optional file path to export predictions.

    Returns:
        (List of ShadowPredictionDTO, manifest dict)
    """
    scored = model.score_population(list(procurements))

    now_iso = datetime.now(timezone.utc).isoformat()
    dtos: List[ShadowPredictionDTO] = []
    band_distribution: Dict[str, int] = {
        BAND_GOLD: 0,
        BAND_SILVER: 0,
        BAND_BRONZE: 0,
        BAND_WOOD: 0,
    }

    for s in scored:
        band = s.priority_band
        band_distribution[band] = band_distribution.get(band, 0) + 1
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
        dtos.append(dto)

    manifest = {
        "model_name": model.model_name,
        "model_version": model.model_version,
        "training_snapshot_sha256": model.dataset_snapshot_sha256,
        "scored_at": now_iso,
        "total_scored": len(dtos),
        "band_distribution": band_distribution,
        "output_file": output_path,
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([d.to_dict() for d in dtos], f, ensure_ascii=False, indent=2)

        manifest_path = f"{output_path}.manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    return dtos, manifest
