"""Queue V2 payload builder (PHASE 2) - read-only until written explicitly.

    CURRENT categories -> DOCUMENT_NEEDS_PLAN_V2 -> selection V2 -> payload

The queue never decides which documents to take; it receives the ready result:
selected_source_document_ids, physical keys, fallback ids and the priority key.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .document_classifier_v1 import classify_document_metadata
from .document_needs_plan_v2 import (
    DOCUMENT_NEEDS_POLICY_VERSION,
    DOCUMENT_SELECTION_POLICY_VERSION,
    SELECTED,
    SELECTED_FALLBACK,
    build_document_needs_plan,
    category_plan,
    select_unit_documents,
)
from .queue_priority_v2 import (
    PRIORITY_POLICY_VERSION,
    compute_queue_priority_v2,
    research_action_for_priority,
)
from .research_action_v2 import (
    RESEARCH_ACTION_POLICY_VERSION,
    ResearchAction,
)

QUEUE_PLAN_VERSION = "queue_v2"
SELECTION_TYPE_NORMAL = "NORMAL"
SELECTION_TYPE_FALLBACK = "FALLBACK"


def physical_key(doc: Dict[str, Any]) -> str:
    return (
        doc.get("physical_download_key")
        or doc.get("url_hash")
        or (doc.get("url") or "").strip().lower()
        or f"row:{doc.get('id')}"
    )


def _dedupe_by_identity(docs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for doc in docs:
        key = physical_key(doc)
        if key not in seen:
            seen[key] = doc
    return list(seen.values())


def build_queue_plan_v2(
    *,
    procurement: Dict[str, Any],
    opportunities: Sequence[Dict[str, Any]],
    documents: Sequence[Dict[str, Any]],
    pipeline_generation: str,
) -> Dict[str, Any]:
    """Build one Queue V2 payload for a procurement (no writes)."""
    procurement_id = int(procurement["id"])
    units: Dict[str, set] = {}
    for opp in opportunities:
        category = opp.get("commercial_category_code") or opp.get("category_code")
        if not category:
            continue
        units.setdefault(category, set()).add(opp.get("opportunity_track"))

    docs = _dedupe_by_identity(documents)
    by_id = {int(d["id"]): d for d in docs if d.get("id") is not None}
    items = [
        (
            doc.get("id"),
            doc.get("file_name") or "",
            classify_document_metadata(doc.get("file_name"), source_table=doc.get("source_table")),
        )
        for doc in docs
        if doc.get("id") is not None
    ]

    selected: Dict[int, Dict[str, Any]] = {}
    required_facts: List[str] = []
    required_classes: List[str] = []
    for category in sorted(units):
        plan = build_document_needs_plan(
            procurement_id,
            [category_plan(category, group) for group in sorted(units[category])],
        )
        for fact in plan.required_facts:
            if fact.value not in required_facts:
                required_facts.append(fact.value)
        for doc_class in plan.required_classes:
            if doc_class.value not in required_classes:
                required_classes.append(doc_class.value)
        selections, _promoted = select_unit_documents(
            plan, procurement_id=procurement_id, category_code=category, documents=items
        )
        for selection in selections:
            if selection.selection_decision not in (SELECTED, SELECTED_FALLBACK):
                continue
            doc_id = selection.source_document_id
            if doc_id is None:
                continue
            entry = selected.setdefault(
                int(doc_id),
                {
                    "source_document_id": int(doc_id),
                    "file_name": selection.file_name,
                    "document_class": selection.document_class.value,
                    "selection_type": (
                        SELECTION_TYPE_FALLBACK
                        if selection.selection_decision == SELECTED_FALLBACK
                        else SELECTION_TYPE_NORMAL
                    ),
                    "selection_reason": selection.selection_reason,
                    "required_by_category": [],
                    "required_facts": list(selection.required_facts),
                },
            )
            if category not in entry["required_by_category"]:
                entry["required_by_category"].append(category)
            for fact in selection.required_facts:
                if fact not in entry["required_facts"]:
                    entry["required_facts"].append(fact)

    all_ids = sorted(selected)
    normal_ids = [i for i in all_ids if selected[i]["selection_type"] == SELECTION_TYPE_NORMAL]
    fallback_ids = [i for i in all_ids if selected[i]["selection_type"] == SELECTION_TYPE_FALLBACK]
    physical_keys = [physical_key(by_id[i]) for i in all_ids if i in by_id]

    best_opp = max(
        opportunities,
        key=lambda o: (
            {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1}.get(
                (o.get("current_effective_medal") or o.get("candidate_initial_medal") or "").upper(), 0
            ),
            int(o.get("commercial_priority_score") or 0),
        ),
        default={},
    )
    priority = compute_queue_priority_v2(
        opportunity_track=best_opp.get("opportunity_track"),
        crm_stage=procurement.get("crm_stage"),
        award_status=procurement.get("award_status"),
        source_status=procurement.get("source_status"),
        start_date=procurement.get("start_date"),
        end_date=procurement.get("end_date"),
        delivery_start_date=procurement.get("delivery_start_date"),
        delivery_end_date=procurement.get("delivery_end_date"),
        execution_start_at=procurement.get("execution_start_at"),
        execution_end_at=procurement.get("execution_end_at"),
        medal=best_opp.get("current_effective_medal") or best_opp.get("candidate_initial_medal"),
        commercial_priority=best_opp.get("commercial_priority_score"),
    )
    base_action = ResearchAction(best_opp.get("research_action_v2_base") or _base_action(opportunities))
    action = research_action_for_priority(priority, base_action)

    return {
        "procurement_id": procurement_id,
        "pipeline_generation": pipeline_generation,
        "plan_version": QUEUE_PLAN_VERSION,
        "priority_policy_version": PRIORITY_POLICY_VERSION,
        "research_action_policy_version": RESEARCH_ACTION_POLICY_VERSION,
        "document_plan_version": DOCUMENT_NEEDS_POLICY_VERSION,
        "selection_policy_version": DOCUMENT_SELECTION_POLICY_VERSION,
        "work_tier": priority.work_tier,
        "source_start_date": procurement.get("start_date"),
        "source_lifecycle": priority.source_lifecycle,
        "project_active": priority.project_active,
        "project_end_at": priority.project_end_at,
        "project_remaining_days": priority.project_remaining_days,
        "execution_phase": priority.execution_phase,
        "candidate_initial_medal": best_opp.get("candidate_initial_medal"),
        "current_effective_medal": best_opp.get("current_effective_medal"),
        "commercial_priority_score": best_opp.get("commercial_priority_score"),
        "research_action_v2": action.value,
        "acquisition_allowed": priority.acquisition_allowed,
        "skip_reason": None if priority.acquisition_allowed else priority.reason,
        "category_codes": sorted(units),
        "required_facts": required_facts,
        "required_document_types": required_classes,
        "selected_source_document_ids": normal_ids + fallback_ids,
        "selected_physical_keys": physical_keys,
        "fallback_source_document_ids": fallback_ids,
        "selected_documents": [selected[i] for i in all_ids],
        "sort_key": priority.sort_key,
    }


def _base_action(opportunities: Sequence[Dict[str, Any]]) -> str:
    order = [
        ResearchAction.DOCUMENT_CONFIRMATION_REQUIRED.value,
        ResearchAction.DOCUMENT_RESEARCH_REQUIRED.value,
        ResearchAction.NO_DOCUMENT_RESEARCH.value,
        ResearchAction.NO_OPPORTUNITY.value,
    ]
    present = {str(o.get("research_action_v2") or "") for o in opportunities}
    for candidate in order:
        if candidate in present:
            return candidate
    return ResearchAction.NO_OPPORTUNITY.value
