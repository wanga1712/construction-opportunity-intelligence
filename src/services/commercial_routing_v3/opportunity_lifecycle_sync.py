"""S7→S13 commercial opportunity lifecycle sync logic (pure compute).

No persistence is performed here. Production writes are handled by a separate wrapper
in a later step; in this WIP we only need deterministic state transitions + audit events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.domain.commercial_opportunity_lifecycle import (
    CommercialOpportunityState,
    SourceLifecycleEvent,
)
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_from_procurement,
)


S13_TRACK_DIRECT_SUPPLY = "DIRECT_SUPPLY"
S13_TRACK_EMBEDDED_MATERIAL = "EMBEDDED_MATERIAL"
S13_TRACK_DESIGN_REQUIREMENT = "DESIGN_REQUIREMENT"
S13_TRACK_DESIGN_INFLUENCE = "DESIGN_INFLUENCE"
S13_TRACK_NO_COMMERCIAL_ENTRY = "NO_COMMERCIAL_ENTRY"
S13_TRACK_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LifecycleDecision:
    source_event: SourceLifecycleEvent
    commercial_state: CommercialOpportunityState
    reason: str


def _source_event_from_crm_procurement(proc: Dict[str, Any]) -> SourceLifecycleEvent:
    """Canonical normalizer — see source_lifecycle.normalize_source_lifecycle_event."""
    return normalize_source_lifecycle_from_procurement(proc)

def _source_priority_for_dominant(proc: Dict[str, Any]) -> int:
    """Higher wins; used to pick the dominant procurement per contract_number."""
    ev = _source_event_from_crm_procurement(proc)
    if ev == SourceLifecycleEvent.AWARDED:
        return 30
    if ev == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME:
        return 20
    if ev == SourceLifecycleEvent.OPEN:
        return 10
    if ev == SourceLifecycleEvent.TERMINAL_NO_RESULT:
        return 5
    return 0


_OBJECT_PROCUREMENT_FORMS = {
    "CONSTRUCTION_WORKS",
    "DESIGN_AND_BUILD",
    "DESIGN_EXPERTISE_AND_BUILD",
    "DESIGN_ONLY",
    "SURVEY_AND_DESIGN",
}


def _procurement_form_from_source(src: Dict[str, Any]) -> str:
    """Form from explicit field or title/OKPD classifier. Empty source → ''."""
    explicit = str(src.get("procurement_form") or "").strip().upper()
    if explicit:
        return explicit
    title = src.get("auction_name") or src.get("title") or ""
    okpd = src.get("okpd_code") or ""
    if not title and not okpd:
        return ""
    from src.services.commercial_routing_v3.procurement_form import classify_procurement_form

    return classify_procurement_form(src).value


def _compute_decision(
    *,
    track: str,
    source_event: SourceLifecycleEvent,
    procurement_form: str = "",
) -> LifecycleDecision:
    track = (track or "").strip()
    form = (procurement_form or "").strip().upper()

    if track == S13_TRACK_NO_COMMERCIAL_ENTRY:
        return LifecycleDecision(
            source_event=source_event,
            commercial_state=CommercialOpportunityState.SUPPRESSED,
            reason="NO_COMMERCIAL_ENTRY",
        )

    if track == S13_TRACK_UNKNOWN:
        if source_event in (SourceLifecycleEvent.OPEN, SourceLifecycleEvent.WAITING_SOURCE_OUTCOME):
            return LifecycleDecision(
                source_event=source_event,
                commercial_state=CommercialOpportunityState.REVIEW_REQUIRED,
                reason="UNKNOWN_TRACK_REVIEW_REQUIRED",
            )
        if source_event == SourceLifecycleEvent.AWARDED:
            return LifecycleDecision(
                source_event=source_event,
                commercial_state=CommercialOpportunityState.ARCHIVED,
                reason="UNKNOWN_TRACK_ARCHIVED_AFTER_AWARDED",
            )
        if source_event == SourceLifecycleEvent.TERMINAL_NO_RESULT:
            return LifecycleDecision(
                source_event=source_event,
                commercial_state=CommercialOpportunityState.STALE_SOURCE,
                reason="UNKNOWN_TRACK_STALE_SOURCE_AFTER_TERMINAL",
            )

        return LifecycleDecision(
            source_event=source_event,
            commercial_state=CommercialOpportunityState.REVIEW_REQUIRED,
            reason="UNKNOWN_TRACK_REVIEW_REQUIRED",
        )

    is_direct_supply = track == S13_TRACK_DIRECT_SUPPLY
    is_followup_tracks = track in (
        S13_TRACK_EMBEDDED_MATERIAL,
        S13_TRACK_DESIGN_REQUIREMENT,
        S13_TRACK_DESIGN_INFLUENCE,
    )

    if is_direct_supply:
        if source_event == SourceLifecycleEvent.OPEN:
            return LifecycleDecision(source_event, CommercialOpportunityState.ACTIVE, "DIRECT_SUPPLY_ACTIVE")
        if source_event == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME:
            return LifecycleDecision(
                source_event, CommercialOpportunityState.WAITING_SOURCE_OUTCOME, "DIRECT_SUPPLY_WAITING"
            )
        if source_event == SourceLifecycleEvent.AWARDED:
            # Object-form + stored DIRECT_SUPPLY is a mis-track: keep post-award follow-up.
            # True DIRECT_GOODS (or unknown form) closes — no new sales opportunity.
            if form in _OBJECT_PROCUREMENT_FORMS:
                return LifecycleDecision(
                    source_event, CommercialOpportunityState.FOLLOW_UP_AWARDED, "FOLLOWUP_AWARDED"
                )
            return LifecycleDecision(source_event, CommercialOpportunityState.CLOSED, "DIRECT_SUPPLY_CLOSED")
        if source_event == SourceLifecycleEvent.TERMINAL_NO_RESULT:
            return LifecycleDecision(
                source_event, CommercialOpportunityState.STALE_SOURCE, "DIRECT_SUPPLY_STALE_TERMINAL"
            )
        return LifecycleDecision(source_event, CommercialOpportunityState.ACTIVE, "DIRECT_SUPPLY_ACTIVE")

    if is_followup_tracks:
        if source_event == SourceLifecycleEvent.OPEN:
            return LifecycleDecision(source_event, CommercialOpportunityState.ACTIVE, "FOLLOWUP_ACTIVE")
        if source_event == SourceLifecycleEvent.WAITING_SOURCE_OUTCOME:
            return LifecycleDecision(
                source_event, CommercialOpportunityState.WAITING_SOURCE_OUTCOME, "FOLLOWUP_WAITING"
            )
        if source_event == SourceLifecycleEvent.AWARDED:
            return LifecycleDecision(
                source_event, CommercialOpportunityState.FOLLOW_UP_AWARDED, "FOLLOWUP_AWARDED"
            )
        if source_event == SourceLifecycleEvent.TERMINAL_NO_RESULT:
            return LifecycleDecision(
                source_event, CommercialOpportunityState.STALE_SOURCE, "FOLLOWUP_STALE_TERMINAL"
            )
        return LifecycleDecision(source_event, CommercialOpportunityState.ACTIVE, "FOLLOWUP_ACTIVE")

    # Unknown track string (not expected)
    return LifecycleDecision(
        source_event=source_event,
        commercial_state=CommercialOpportunityState.REVIEW_REQUIRED,
        reason="UNEXPECTED_TRACK_REVIEW_REQUIRED",
    )


def compute_opportunity_lifecycle_updates(
    *,
    source_procurements: List[Dict[str, Any]],
    opportunities: List[Dict[str, Any]],
    existing_audit: Iterable[Dict[str, Any]] = (),
    now: Optional[datetime] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pure function.

    Args:
      source_procurements: list of {procurement_id, source_table, source_id, contract_number, crm_stage, award_status}.
      opportunities: list of current opportunity rows with at least:
         {id, procurement_id, commercial_category_code, commercial_subcategory_code, opportunity_track,
          commercial_state, last_source_event}
      existing_audit: existing audit entries (used for idempotence).
    """

    if now is None:
        now = datetime.utcnow()

    source_by_proc_id: Dict[int, Dict[str, Any]] = {
        int(p["procurement_id"]): p for p in source_procurements if p.get("procurement_id") is not None
    }

    def _stable_identity_key(src: Dict[str, Any]) -> Optional[str]:
        source_table = (src.get("source_table") or "").strip()
        source_id = src.get("source_id", None)
        source_contour = resolve_source_contour(
            source_table=source_table, law_type=src.get("law_type") or ""
        )
        cn = (src.get("contract_number") or "")
        cn_s = cn.strip()
        if cn_s:
            return f"{source_contour.value}:CN:{cn_s}"
        # Contract number absent/empty -> fallback to native source identity to avoid false dedupe.
        if source_id is not None:
            return f"{source_contour.value}:SRC:{source_table}:{int(source_id)}"
        return f"{source_contour.value}:PROC:{int(src.get('procurement_id'))}"

    # Pick dominant procurement per stable identity key to prevent duplicates.
    procs_by_stable_id: Dict[str, List[Dict[str, Any]]] = {}
    for p in source_procurements:
        key = _stable_identity_key(p)
        if not key:
            continue
        procs_by_stable_id.setdefault(key, []).append(p)

    dominant_procurement_id_by_stable_id: Dict[str, int] = {}
    for stable_id, procs in procs_by_stable_id.items():
        best = max(procs, key=_source_priority_for_dominant)
        dominant_procurement_id_by_stable_id[stable_id] = int(best["procurement_id"])

    existing_keys = set()
    for row in existing_audit:
        # A key that is stable enough for idempotence in this compute layer.
        key = (
            row.get("opportunity_id"),
            row.get("old_commercial_state"),
            row.get("new_commercial_state"),
            row.get("old_source_event"),
            row.get("new_source_event"),
            row.get("reason"),
        )
        existing_keys.add(key)

    updated_opps: List[Dict[str, Any]] = []
    new_audit: List[Dict[str, Any]] = []

    for opp in opportunities:
        opp = dict(opp)
        opp_id = opp.get("id")
        procurement_id = opp.get("procurement_id")
        track = opp.get("opportunity_track") or ""

        old_state = opp.get("commercial_state")
        old_source_event = opp.get("last_source_event")

        src = source_by_proc_id.get(int(procurement_id)) if procurement_id is not None else None
        if src is None:
            # Temporary gap must not archive/delete; only mark sync status.
            opp["source_sync_status"] = "MISSING"
            if opp.get("source_missing_since") is None:
                opp["source_missing_since"] = now
            updated_opps.append(opp)
            continue

        source_table = src.get("source_table") or ""
        source_contour = resolve_source_contour(
            source_table=source_table, law_type=src.get("law_type") or ""
        )
        stable_key = _stable_identity_key(src) or ""
        src_event = _source_event_from_crm_procurement(src)

        dominant_id = dominant_procurement_id_by_stable_id.get(stable_key)
        if dominant_id is not None and int(procurement_id) != int(dominant_id):
            # This procurement is not the dominant stable identity state.
            new_state = CommercialOpportunityState.STALE_SOURCE
            new_source_event = src_event
            reason = "S7_DUPLICATE_SUPPRESSED"
        else:
            decision = _compute_decision(
                track=track,
                source_event=src_event,
                procurement_form=_procurement_form_from_source(src),
            )
            new_state = decision.commercial_state
            new_source_event = decision.source_event
            reason = decision.reason

        # Update last_source_event seen metadata.
        opp["last_source_event"] = new_source_event.value
        opp["last_source_seen_at"] = now
        opp["source_missing_since"] = None
        opp["source_sync_status"] = "OK"

        # Record audit if anything meaningful changed.
        old_state_s = (old_state or "").strip()
        new_state_s = new_state.value
        old_source_s = (old_source_event or "").strip()
        new_source_s = new_source_event.value

        state_changed = old_state_s != new_state_s
        source_changed = old_source_s != new_source_s

        if state_changed:
            opp["commercial_state"] = new_state_s

        if state_changed or source_changed:
            audit_key = (
                opp_id,
                old_state_s or None,
                new_state_s,
                old_source_s or None,
                new_source_s,
                reason,
            )
            if audit_key not in existing_keys:
                new_audit.append(
                    {
                        "procurement_id": procurement_id,
                        "opportunity_id": opp_id,
                        "commercial_category_code": opp.get("commercial_category_code"),
                        "commercial_subcategory_code": opp.get("commercial_subcategory_code"),
                        "opportunity_track": track,
                        "old_source_event": old_source_s or None,
                        "new_source_event": new_source_s,
                        "old_commercial_state": old_state_s or None,
                        "new_commercial_state": new_state_s,
                        "reason": reason,
                        "source_seen_at": now,
                        "changed_at": now,
                    }
                )

        updated_opps.append(opp)

    # Keep deterministic ordering (use opportunity id if present)
    updated_opps.sort(key=lambda r: int(r.get("id") or 0))
    return updated_opps, new_audit


def sync_opportunities_lifecycle(
    crm_db,
    *,
    dry_run: bool = True,
    now: Optional[datetime] = None,
    limit: int = 5000,
) -> Dict[str, Any]:
    """DB wrapper for opportunity lifecycle transitions.

    Safe defaults:
      - dry_run=True (no persistence)
      - limit on number of opportunities
    """
    if now is None:
        now = datetime.utcnow()

    # 0) Schema guard (table may not exist yet in production cutover)
    try:
        regclass = crm_db.execute_scalar(
            "SELECT to_regclass('public.crm_procurement_category_opportunities')"
        )
    except Exception:
        regclass = None
    if not regclass:
        return {
            "dry_run": dry_run,
            "updated": 0,
            "transitions": 0,
            "skipped": 1,
            "reason": "category_opportunities_table_missing",
        }

    # 1) Current opportunities
    opp_rows = crm_db.execute_query(
        """
        SELECT
            id,
            procurement_id,
            commercial_category_code,
            commercial_subcategory_code,
            opportunity_track,
            commercial_state,
            last_source_event,
            source_sync_status,
            source_missing_since
        FROM crm_procurement_category_opportunities
        WHERE status = 'CURRENT'
        ORDER BY id
        LIMIT %s
        """,
        (limit,),
    ) or []

    opp_rows = [dict(r) if isinstance(r, dict) else {} for r in opp_rows]
    if not opp_rows:
        return {"dry_run": dry_run, "updated": 0, "transitions": 0, "skipped": 0}

    procurement_ids = [int(r["procurement_id"]) for r in opp_rows if r.get("procurement_id") is not None]

    # 2) Source lifecycle from crm_procurements (S7-derived copy)
    src_rows = crm_db.execute_query(
        """
        SELECT
            id AS procurement_id,
            source_table,
            source_id,
            contract_number,
            crm_stage,
            award_status,
            auction_name,
            okpd_code,
            okpd_name
        FROM crm_procurements
        WHERE id = ANY(%s)
        """,
        (procurement_ids,),
    ) or []
    src_rows = [dict(r) if isinstance(r, dict) else {} for r in src_rows]

    # 3) Existing audit rows for idempotence
    opp_ids = [int(r["id"]) for r in opp_rows if r.get("id") is not None]
    existing_audit = crm_db.execute_query(
        """
        SELECT
            opportunity_id,
            old_source_event,
            new_source_event,
            old_commercial_state,
            new_commercial_state,
            reason
        FROM crm_category_opportunity_lifecycle_audit
        WHERE opportunity_id = ANY(%s)
        """,
        (opp_ids,),
    ) or []
    existing_audit = [dict(r) if isinstance(r, dict) else {} for r in existing_audit]

    updated_opps, new_audit = compute_opportunity_lifecycle_updates(
        source_procurements=src_rows,
        opportunities=opp_rows,
        existing_audit=existing_audit,
        now=now,
    )

    if dry_run:
        return {
            "dry_run": True,
            "updated": len(updated_opps),
            "transitions": len(new_audit),
            "skipped": 0,
        }

    # 4) Persist changes + transitions
    # Opportunities: update all relevant columns.
    for o in updated_opps:
        crm_db.execute_update(
            """
            UPDATE crm_procurement_category_opportunities
            SET
                commercial_state   = %s,
                last_source_event  = %s,
                last_source_seen_at = %s,
                source_missing_since = %s,
                source_sync_status  = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                o.get("commercial_state"),
                o.get("last_source_event"),
                o.get("last_source_seen_at"),
                o.get("source_missing_since"),
                o.get("source_sync_status"),
                o.get("id"),
            ),
        )

    # Transition audit inserts
    for t in new_audit:
        crm_db.execute_update(
            """
            INSERT INTO crm_category_opportunity_lifecycle_audit (
                procurement_id, opportunity_id,
                commercial_category_code, commercial_subcategory_code, opportunity_track,
                old_source_event, new_source_event,
                old_commercial_state, new_commercial_state,
                reason, source_seen_at, routing_version, registry_version, registry_hash
            ) VALUES (
                %s,%s,%s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,%s,%s
            )
            """,
            (
                t.get("procurement_id"),
                t.get("opportunity_id"),
                t.get("commercial_category_code"),
                t.get("commercial_subcategory_code"),
                t.get("opportunity_track"),
                t.get("old_source_event"),
                t.get("new_source_event"),
                t.get("old_commercial_state"),
                t.get("new_commercial_state"),
                t.get("reason"),
                t.get("source_seen_at"),
                t.get("routing_version", "v3"),
                t.get("registry_version"),
                t.get("registry_hash"),
            ),
        )

    return {"dry_run": False, "updated": len(updated_opps), "transitions": len(new_audit), "skipped": 0}

