"""Shadow Prediction DTO and repository interfaces for OKPD prior research priority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ShadowPredictionDTO:
    """Immutable prediction DTO for shadow procurement research priority."""
    procurement_id: int
    model_name: str
    model_version: str
    trained_at: Optional[str]
    dataset_snapshot_sha256: Optional[str]
    p_research_hit: float
    priority_percentile: float
    priority_band: str
    okpd_code_raw: Optional[str]
    okpd_root: str
    okpd_level2: str
    okpd_level3: str
    okpd_full: str
    prediction_created_at: str
    shadow_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShadowPredictionDTO":
        return cls(
            procurement_id=int(data["procurement_id"]),
            model_name=str(data["model_name"]),
            model_version=str(data["model_version"]),
            trained_at=data.get("trained_at"),
            dataset_snapshot_sha256=data.get("dataset_snapshot_sha256"),
            p_research_hit=float(data["p_research_hit"]),
            priority_percentile=float(data["priority_percentile"]),
            priority_band=str(data["priority_band"]),
            okpd_code_raw=data.get("okpd_code_raw"),
            okpd_root=str(data.get("okpd_root", "")),
            okpd_level2=str(data.get("okpd_level2", "")),
            okpd_level3=str(data.get("okpd_level3", "")),
            okpd_full=str(data.get("okpd_full", "")),
            prediction_created_at=str(
                data.get("prediction_created_at")
                or datetime.now(timezone.utc).isoformat()
            ),
            shadow_only=bool(data.get("shadow_only", True)),
        )
