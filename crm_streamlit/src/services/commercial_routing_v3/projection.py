"""V3 CRM projection: lifecycle identity, admission, visibility.

Production writer: src.services.commercial_routing_v3.projection_writer
wired via scripts/run_crm_sync.py (legacy sync_all_processed is not production).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.domain.commercial_opportunity_lifecycle import CommercialOpportunityState
from src.domain.commercial_routing_v3 import SourceContour
from src.services.commercial_routing_v3.source_contour import resolve_source_contour


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------

ENV_V3_PROJECTION_ENABLED = "CRM_V3_PROJECTION_ENABLED"


def v3_projection_enabled() -> bool:
    """Production default OFF — fail-closed until cutover enables it."""
    return os.getenv(ENV_V3_PROJECTION_ENABLED, "0") == "1"


V3_PROJECTION_DEFAULT_ENABLED = False
V3_PROJECTION_PARALLEL_LEGACY_WRITER = False
TARGET_PROJECTION_USES_S7_PROCESSED_DOCUMENTS = False
LEGACY_COMMERCIAL_FILTER_BEFORE_V3 = False
FULL_AWARDED_HISTORY_IMPORTED = False
CRM_IS_FULL_SOURCE_MIRROR = False
RAW_PROJECTED_PROCUREMENT_IS_ACTIVE_LEAD = False
OPEN_REQUIRES_DOCS_PROCESSED = False
OPEN_REQUIRES_USER_OKPD = False
OPEN_REQUIRES_KEYWORD_MATCH = False


# ---------------------------------------------------------------------------
# Contract number + lifecycle identity
# ---------------------------------------------------------------------------

def normalize_contract_number(value: Any) -> Optional[str]:
    """Trim whitespace; empty → None. Never numeric-cast; keep leading zeroes."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


@dataclass(frozen=True)
class LifecycleIdentity:
    """Canonical CRM procurement identity across OPEN→COMMISSION→AWARDED."""

    source_contour: SourceContour
    contract_number: Optional[str]
    # Fallback components — only when contract_number is None
    source_table: Optional[str] = None
    source_id: Optional[int] = None
    uses_fallback: bool = False

    def key(self) -> Tuple:
        if self.contract_number:
            return ("stable", self.source_contour.value, self.contract_number)
        return (
            "fallback",
            self.source_contour.value,
            self.source_table or "",
            int(self.source_id or 0),
        )


class NotProjectedReason(StrEnum):
    UNSUPPORTED_CONTOUR = "UNSUPPORTED_CONTOUR"
    MISSING_IDENTITY = "MISSING_IDENTITY"
    MALFORMED_SOURCE_ROW = "MALFORMED_SOURCE_ROW"
    FULL_AWARDED_HISTORY_EXCLUDED = "FULL_AWARDED_HISTORY_EXCLUDED"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"


class SourceStage(StrEnum):
    OPEN = "OPEN"
    WAITING_SOURCE_OUTCOME = "WAITING_SOURCE_OUTCOME"
    AWARDED = "AWARDED"


class ProcurementRoutingState(StrEnum):
    """Derived routing posture for a projected procurement (not commercial lead)."""

    PENDING_ROUTING = "PENDING_ROUTING"
    ROUTED = "ROUTED"
    NO_CURRENT_OPPORTUNITY = "NO_CURRENT_OPPORTUNITY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


VISIBLE_OPPORTUNITY_STATES = frozenset(
    {
        CommercialOpportunityState.ACTIVE.value,
        CommercialOpportunityState.FOLLOW_UP_AWARDED.value,
    }
)

# Minimal core fields projected into CRM (not full S7 row).
PROJECTED_CORE_FIELDS: Tuple[str, ...] = (
    "id",
    "source_contour",
    "source_table",
    "source_id",
    "contract_number",
    "auction_name",
    "okpd_code",
    "okpd_name",
    "customer",
    "delivery_region",
    "region_id",
    "initial_price",
    "final_price",
    "start_date",
    "end_date",
    "delivery_start_date",
    "delivery_end_date",
    "tender_link",
    "crm_stage",
    "award_status",
    "winner_name",
    "winner_inn",
    "final_contract_price",
    "contract_signed_at",
    "execution_start_at",
    "execution_end_at",
    "source_awarded_table",
    "source_awarded_id",
    "source_updated_at",
    "ai_assessment_status",  # routing posture carrier when V3 enabled
)

PROJECTED_CORE_FIELDS_COUNT = len(PROJECTED_CORE_FIELDS)


def stage_from_source_table(source_table: str) -> SourceStage:
    t = (source_table or "").lower()
    if "commission" in t:
        return SourceStage.WAITING_SOURCE_OUTCOME
    if "awarded" in t:
        return SourceStage.AWARDED
    return SourceStage.OPEN


def resolve_lifecycle_identity(
    *,
    source_table: str,
    source_id: Any,
    contract_number: Any,
    law_type: str = "",
) -> LifecycleIdentity:
    contour = resolve_source_contour(source_table=source_table, law_type=law_type)
    cn = normalize_contract_number(contract_number)
    sid = int(source_id) if source_id is not None else None
    if cn:
        return LifecycleIdentity(
            source_contour=contour,
            contract_number=cn,
            source_table=source_table,
            source_id=sid,
            uses_fallback=False,
        )
    return LifecycleIdentity(
        source_contour=contour,
        contract_number=None,
        source_table=source_table,
        source_id=sid,
        uses_fallback=True,
    )


# ---------------------------------------------------------------------------
# Identity upgrade policy (fallback → stable)
# ---------------------------------------------------------------------------

FALLBACK_TO_STABLE_IDENTITY_POLICY = """
When a row was first projected with fallback identity
(source_contour, source_table, source_id) and a non-empty contract_number
later appears:

1. If the same CRM row's provenance (source_table/source_id or awarded
   provenance) proves equivalence → UPGRADE that row's stable identity
   in place (preserve crm_procurements.id).
2. If a different CRM row already owns the stable
   (source_contour, contract_number) → REVIEW_REQUIRED (no silent merge).
3. If equivalence cannot be proven → REVIEW_REQUIRED (no guess merge).
""".strip()


class IdentityUpgradeResult(StrEnum):
    UPGRADED = "UPGRADED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOOP = "NOOP"


def decide_fallback_identity_upgrade(
    *,
    existing_row: Dict[str, Any],
    new_contract_number: Any,
    stable_owner_id: Optional[int] = None,
) -> IdentityUpgradeResult:
    """Safe upgrade of fallback row when contract_number appears."""
    cn = normalize_contract_number(new_contract_number)
    if not cn:
        return IdentityUpgradeResult.NOOP
    if normalize_contract_number(existing_row.get("contract_number")):
        return IdentityUpgradeResult.NOOP
    if stable_owner_id is not None and int(stable_owner_id) != int(existing_row["id"]):
        return IdentityUpgradeResult.REVIEW_REQUIRED
    # Provenance equivalence: caller must only invoke when same source_id/table lineage
    return IdentityUpgradeResult.UPGRADED


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdmissionDecision:
    admit: bool
    reason: Optional[NotProjectedReason] = None
    stage: Optional[SourceStage] = None


def admit_source_row(
    *,
    source_table: str,
    source_id: Any,
    contract_number: Any,
    auction_name: Any = None,
    source_updated_at: Any = None,
    awarded_watermark: Any = None,
    crm_has_lifecycle_identity: bool = False,
    law_type: str = "",
    enabled: Optional[bool] = None,
) -> AdmissionDecision:
    """Stage-based technical admission. No docs/OKPD/keyword commercial filters."""
    if enabled is None:
        enabled = v3_projection_enabled()
    if not enabled:
        return AdmissionDecision(False, NotProjectedReason.FEATURE_DISABLED)

    contour = resolve_source_contour(source_table=source_table, law_type=law_type)
    if contour == SourceContour.UNKNOWN:
        return AdmissionDecision(False, NotProjectedReason.UNSUPPORTED_CONTOUR)

    stage = stage_from_source_table(source_table)
    cn = normalize_contract_number(contract_number)
    title = (str(auction_name).strip() if auction_name is not None else "")

    if source_id is None and not cn:
        return AdmissionDecision(False, NotProjectedReason.MISSING_IDENTITY, stage)

    if stage == SourceStage.OPEN:
        if not title:
            return AdmissionDecision(False, NotProjectedReason.MALFORMED_SOURCE_ROW, stage)
        return AdmissionDecision(True, None, stage)

    if stage == SourceStage.WAITING_SOURCE_OUTCOME:
        # Minimal projection allowed for later embedded/design follow-up
        return AdmissionDecision(True, None, stage)

    # AWARDED: existing CRM identity OR incremental after watermark only
    if crm_has_lifecycle_identity:
        return AdmissionDecision(True, None, stage)
    if awarded_watermark is not None and source_updated_at is not None:
        if source_updated_at > awarded_watermark:
            return AdmissionDecision(True, None, stage)
    return AdmissionDecision(False, NotProjectedReason.FULL_AWARDED_HISTORY_EXCLUDED, stage)


# ---------------------------------------------------------------------------
# Routing state + commercial visibility
# ---------------------------------------------------------------------------

def routing_state_from_ai_status(
    ai_assessment_status: Optional[str],
    *,
    has_visible_opportunity: bool = False,
    discovery_required: bool = False,
    skip_no_opportunity: bool = False,
) -> ProcurementRoutingState:
    status = (ai_assessment_status or "UNASSESSED").upper()
    if status in ("FAILED", "MANUAL_REVIEW") or status == "REVIEW_REQUIRED":
        return ProcurementRoutingState.REVIEW_REQUIRED
    if has_visible_opportunity:
        return ProcurementRoutingState.ROUTED
    if skip_no_opportunity and not discovery_required:
        return ProcurementRoutingState.NO_CURRENT_OPPORTUNITY
    if discovery_required:
        # Remains researchable — still pending routing / discovery lane
        return ProcurementRoutingState.PENDING_ROUTING
    if status in ("UNASSESSED", "RUNNING", ""):
        return ProcurementRoutingState.PENDING_ROUTING
    if status == "COMPLETED":
        return ProcurementRoutingState.NO_CURRENT_OPPORTUNITY
    return ProcurementRoutingState.PENDING_ROUTING


def opportunity_is_visible(commercial_state: str) -> bool:
    return (commercial_state or "") in VISIBLE_OPPORTUNITY_STATES


def active_feed_includes_procurement(
    opportunities: Sequence[Dict[str, Any]],
    *,
    v3_schema_ready: bool,
) -> bool:
    """Active sales feed: requires ≥1 visible opportunity when V3 ready.

    If V3 schema not ready → caller must keep legacy UI (this helper returns
    False for opportunity-gated feed so new projected rows do not flood).
    """
    if not v3_schema_ready:
        return False
    for opp in opportunities:
        state = opp.get("commercial_state") or opp.get("status") or ""
        if opportunity_is_visible(str(state)):
            return True
    return False


def container_visible_from_opportunities(
    opportunities: Sequence[Dict[str, Any]],
) -> bool:
    """Container stays visible if any child opportunity is commercially visible."""
    return any(
        opportunity_is_visible(str(o.get("commercial_state") or o.get("status") or ""))
        for o in opportunities
    )


# ---------------------------------------------------------------------------
# Upsert abstraction (in-memory / injectable store) — not wired to production
# ---------------------------------------------------------------------------

@dataclass
class ProjectionAuditEvent:
    crm_procurement_id: int
    lifecycle_key: Tuple
    old_source_table: Optional[str]
    old_source_id: Optional[int]
    new_source_table: str
    new_source_id: int
    old_stage: Optional[str]
    new_stage: str
    timestamp: datetime


@dataclass
class InMemoryProjectionStore:
    rows: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    by_lifecycle: Dict[Tuple, int] = field(default_factory=dict)
    audit: List[ProjectionAuditEvent] = field(default_factory=list)
    _next_id: int = 1

    def find_by_lifecycle(self, ident: LifecycleIdentity) -> Optional[Dict[str, Any]]:
        rid = self.by_lifecycle.get(ident.key())
        return self.rows.get(rid) if rid is not None else None

    def upsert(self, *, source_row: Dict[str, Any], ident: LifecycleIdentity) -> Dict[str, Any]:
        stage = stage_from_source_table(str(source_row.get("source_table") or ""))
        existing = self.find_by_lifecycle(ident)
        now = datetime.now(timezone.utc)
        if existing is None:
            rid = self._next_id
            self._next_id += 1
            row = {
                "id": rid,
                "source_contour": ident.source_contour.value,
                "contract_number": ident.contract_number,
                "source_table": source_row.get("source_table"),
                "source_id": source_row.get("source_id"),
                "crm_stage": stage.value,
                "ai_assessment_status": "UNASSESSED",
                "auction_name": source_row.get("auction_name"),
            }
            self.rows[rid] = row
            self.by_lifecycle[ident.key()] = rid
            self.audit.append(
                ProjectionAuditEvent(
                    crm_procurement_id=rid,
                    lifecycle_key=ident.key(),
                    old_source_table=None,
                    old_source_id=None,
                    new_source_table=str(source_row.get("source_table")),
                    new_source_id=int(source_row.get("source_id")),
                    old_stage=None,
                    new_stage=stage.value,
                    timestamp=now,
                )
            )
            return row

        old = dict(existing)
        existing["source_table"] = source_row.get("source_table")
        existing["source_id"] = source_row.get("source_id")
        existing["crm_stage"] = stage.value
        if source_row.get("auction_name"):
            existing["auction_name"] = source_row.get("auction_name")
        if ident.contract_number and not existing.get("contract_number"):
            existing["contract_number"] = ident.contract_number
        self.audit.append(
            ProjectionAuditEvent(
                crm_procurement_id=int(existing["id"]),
                lifecycle_key=ident.key(),
                old_source_table=old.get("source_table"),
                old_source_id=old.get("source_id"),
                new_source_table=str(source_row.get("source_table")),
                new_source_id=int(source_row.get("source_id")),
                old_stage=old.get("crm_stage"),
                new_stage=stage.value,
                timestamp=now,
            )
        )
        return existing


def project_source_row(
    store: InMemoryProjectionStore,
    source_row: Dict[str, Any],
    *,
    awarded_watermark: Any = None,
    crm_has_lifecycle_identity: bool = False,
    enabled: Optional[bool] = None,
) -> Tuple[Optional[Dict[str, Any]], AdmissionDecision]:
    """Target writer: one lifecycle upsert. Not used by production timer."""
    ident = resolve_lifecycle_identity(
        source_table=str(source_row.get("source_table") or ""),
        source_id=source_row.get("source_id"),
        contract_number=source_row.get("contract_number"),
        law_type=str(source_row.get("law_type") or ""),
    )
    if store.find_by_lifecycle(ident) is not None:
        crm_has_lifecycle_identity = True

    decision = admit_source_row(
        source_table=str(source_row.get("source_table") or ""),
        source_id=source_row.get("source_id"),
        contract_number=source_row.get("contract_number"),
        auction_name=source_row.get("auction_name"),
        source_updated_at=source_row.get("source_updated_at") or source_row.get("updated_at"),
        awarded_watermark=awarded_watermark,
        crm_has_lifecycle_identity=crm_has_lifecycle_identity,
        law_type=str(source_row.get("law_type") or ""),
        enabled=enabled,
    )
    if not decision.admit:
        return None, decision
    row = store.upsert(source_row=source_row, ident=ident)
    return row, decision
