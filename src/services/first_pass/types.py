"""Data structures and types for the unified First Pass metadata pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FirstPassResult:
    """Canonical First Pass result evaluated strictly from metadata before document research."""
    procurement_id: int
    contract_number: Optional[str] = None
    object_family: str = "OTHER"  # DIRECT_SUPPLY, SOCIAL, COMMERCIAL, OTHER
    object_type: Optional[str] = None
    object_subtype: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    canonical_preliminary_medal: str = "UNASSESSED"  # GOLD, SILVER, BRONZE, WOOD, UNASSESSED
    canonical_preliminary_score: float = 0.0  # 0.0 .. 100.0 (normalized)
    canonical_preliminary_source: str = "UNASSESSED"  # CATEGORY_OPPORTUNITY, AI_ASSESSMENT, OKPD_PRIOR, UNASSESSED
    raw_source_confidence: Optional[float] = None  # traceable original score / confidence
    category_opportunity_count: int = 0
    selected_opportunity_id: Optional[int] = None
    download_decision: str = "DOWNLOAD_DEFER"  # DOWNLOAD_REQUIRED, DOWNLOAD_DEFER, DOWNLOAD_SKIP, NO_LINKS
    medal_base: int = 20
    urgency_bonus: int = 0
    relevance_bonus: int = 0
    priority_score: int = 20  # 0 .. 100 projected into document_processing_queue
    priority_class: str = "UNASSESSED"
    submission_end_at: Optional[datetime] = None
    days_to_deadline: Optional[float] = None
    queue_lane: str = "open_active"
    queue_status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procurement_id": self.procurement_id,
            "contract_number": self.contract_number,
            "category_opportunity_count": self.category_opportunity_count,
            "selected_opportunity_id": self.selected_opportunity_id,
            "object_family": self.object_family,
            "object_type": self.object_type,
            "object_subtype": self.object_subtype,
            "category": self.category,
            "subcategory": self.subcategory,
            "canonical_preliminary_medal": self.canonical_preliminary_medal,
            "canonical_preliminary_score": self.canonical_preliminary_score,
            "canonical_preliminary_source": self.canonical_preliminary_source,
            "raw_source_confidence": self.raw_source_confidence,
            "download_decision": self.download_decision,
            "submission_end_at": self.submission_end_at.isoformat() if self.submission_end_at else None,
            "days_to_deadline": self.days_to_deadline,
            "medal_base": self.medal_base,
            "urgency_bonus": self.urgency_bonus,
            "relevance_bonus": self.relevance_bonus,
            "priority_score": self.priority_score,
            "priority_class": self.priority_class,
            "queue_lane": self.queue_lane,
            "queue_status": self.queue_status,
        }
