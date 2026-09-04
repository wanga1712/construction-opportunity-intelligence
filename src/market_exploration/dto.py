"""Data Transfer Objects for Market Exploration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional


def generate_exploration_run_key(
    run_date: str,
    policy_version: str = "v1",
    source_snapshot_id: str = "live_db",
) -> str:
    """Generates deterministic run_key for daily idempotency."""
    raw = f"{run_date}:{policy_version}:{source_snapshot_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class MarketClusterProfile:
    """Aggregated profile and exploration metrics for a market category/cluster."""
    cluster_key: str
    cluster_level: str  # OKPD_ROOT, OKPD_LEVEL2, OKPD_LEVEL3, OKPD_FULL, PRODUCT_CATEGORY
    parent_key: Optional[str] = None
    procurement_count: int = 0
    total_market_value: float = 0.0
    median_contract_value: float = 0.0
    p25_contract_value: float = 0.0
    p75_contract_value: float = 0.0
    researched_count: int = 0
    positive_count: int = 0
    safe_negative_count: int = 0
    unresolved_count: int = 0
    research_coverage: float = 0.0
    distinct_customers: int = 0
    distinct_regions: int = 0
    uncertainty_score: float = 1.0
    market_volume_score: float = 0.0
    execution_simplicity_estimate: float = 0.5
    repeatability_estimate: float = 0.5
    research_cost_estimate: float = 1.0
    child_cluster_count: int = 0
    unseen_child_cluster_count: int = 0
    exploration_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketClusterProfile":
        return cls(**data)


@dataclass
class ExplorationBudgetDTO:
    """Resource budget constraints for an exploration cycle."""
    max_clusters_per_run: int = 10
    max_procurements_per_cluster: int = 5
    max_total_procurements: int = 50
    max_document_downloads: int = 100
    max_bytes: int = 100_000_000
    max_runtime_seconds: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplorationBudgetDTO":
        return cls(**data)


@dataclass
class ExplorationPlanItemDTO:
    """Individual procurement candidate selected for exploratory research."""
    plan_id: str
    cluster_key: str
    cluster_level: str
    procurement_id: int
    title: str
    okpd_code: str
    lot_price: float
    exploration_priority: float
    reason: str
    selection_stratum: str = "GENERAL"  # LOW_VALUE, MED_VALUE, HIGH_VALUE, DIVERSE_CHILD

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplorationPlanItemDTO":
        return cls(**data)


@dataclass
class ExplorationPlanDTO:
    """Complete budget-constrained market exploration plan."""
    plan_id: str
    run_key: str = ""
    run_date: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_clusters_targeted: int = 0
    total_procurements_targeted: int = 0
    estimated_bytes: int = 0
    estimated_cost: float = 0.0
    items: List[ExplorationPlanItemDTO] = field(default_factory=list)
    budget: ExplorationBudgetDTO = field(default_factory=ExplorationBudgetDTO)
    is_dry_run: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "run_key": self.run_key,
            "run_date": self.run_date,
            "generated_at": self.generated_at,
            "total_clusters_targeted": self.total_clusters_targeted,
            "total_procurements_targeted": self.total_procurements_targeted,
            "estimated_bytes": self.estimated_bytes,
            "estimated_cost": self.estimated_cost,
            "items": [item.to_dict() for item in self.items],
            "budget": self.budget.to_dict(),
            "is_dry_run": self.is_dry_run,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplorationPlanDTO":
        items = [ExplorationPlanItemDTO.from_dict(i) for i in data.get("items", [])]
        budget = ExplorationBudgetDTO.from_dict(data.get("budget", {})) if data.get("budget") else ExplorationBudgetDTO()
        return cls(
            plan_id=str(data["plan_id"]),
            run_key=str(data.get("run_key", "")),
            run_date=str(data.get("run_date", "")),
            generated_at=str(data.get("generated_at") or datetime.now(timezone.utc).isoformat()),
            total_clusters_targeted=int(data.get("total_clusters_targeted", len(items))),
            total_procurements_targeted=int(data.get("total_procurements_targeted", len(items))),
            estimated_bytes=int(data.get("estimated_bytes", 0)),
            estimated_cost=float(data.get("estimated_cost", 0.0)),
            items=items,
            budget=budget,
            is_dry_run=bool(data.get("is_dry_run", True)),
            metadata=dict(data.get("metadata", {})),
        )
