"""Data transfer models and domain entities for Superuser Research Taxonomy."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


MODE_BOOST = "BOOST"
MODE_DOWNWEIGHT = "DOWNWEIGHT"
MODE_NEUTRAL = "NEUTRAL"
MODE_EXPLORE = "EXPLORE"
MODE_EXCLUDE_FROM_PRIMARY = "EXCLUDE_FROM_PRIMARY"

VALID_RULE_MODES = {
    MODE_BOOST,
    MODE_DOWNWEIGHT,
    MODE_NEUTRAL,
    MODE_EXPLORE,
    MODE_EXCLUDE_FROM_PRIMARY,
}

PROPOSAL_STATUS_PENDING = "PENDING"
PROPOSAL_STATUS_APPROVED = "APPROVED"
PROPOSAL_STATUS_REJECTED = "REJECTED"


@dataclass
class TaxonomyRuleDTO:
    """Superuser-managed OKPD prioritization rule."""
    rule_id: str
    okpd_pattern: str
    rule_mode: str
    adjustment_weight: float
    reason: str
    created_by: str
    created_at: str
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxonomyRuleDTO":
        return cls(
            rule_id=str(data["rule_id"]),
            okpd_pattern=str(data["okpd_pattern"]).strip(),
            rule_mode=str(data.get("rule_mode", MODE_NEUTRAL)),
            adjustment_weight=float(data.get("adjustment_weight", 0.0)),
            reason=str(data.get("reason", "")),
            created_by=str(data.get("created_by", "system")),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
            is_active=bool(data.get("is_active", True)),
        )


@dataclass
class TaxonomyProposalDTO:
    """Evidence-derived proposal for superuser review."""
    proposal_id: str
    okpd_pattern: str
    proposed_mode: str
    proposed_adjustment: float
    evidence_summary: str
    positive_count: int
    negative_count: int
    sample_pids: List[int]
    status: str = PROPOSAL_STATUS_PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxonomyProposalDTO":
        return cls(
            proposal_id=str(data["proposal_id"]),
            okpd_pattern=str(data["okpd_pattern"]).strip(),
            proposed_mode=str(data.get("proposed_mode", MODE_NEUTRAL)),
            proposed_adjustment=float(data.get("proposed_adjustment", 0.0)),
            evidence_summary=str(data.get("evidence_summary", "")),
            positive_count=int(data.get("positive_count", 0)),
            negative_count=int(data.get("negative_count", 0)),
            sample_pids=[int(p) for p in data.get("sample_pids", [])],
            status=str(data.get("status", PROPOSAL_STATUS_PENDING)),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
            reviewed_by=data.get("reviewed_by"),
            reviewed_at=data.get("reviewed_at"),
        )


@dataclass
class TaxonomyAuditLogDTO:
    """Audit log entry for superuser taxonomy modifications."""
    log_id: str
    rule_id: str
    action: str
    actor: str
    details: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxonomyAuditLogDTO":
        return cls(
            log_id=str(data["log_id"]),
            rule_id=str(data["rule_id"]),
            action=str(data["action"]),
            actor=str(data["actor"]),
            details=str(data.get("details", "")),
            timestamp=str(data.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        )
