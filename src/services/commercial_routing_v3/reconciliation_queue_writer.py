"""Persist one executable procurement-level Queue V2 plan."""
from __future__ import annotations

from typing import Any

import psycopg2.extras
from psycopg2 import sql


def write_queue_plan(
    cur: Any,
    *,
    row: dict | None,
    source: dict,
    priority: dict,
    plan: dict,
    generation: str,
    reason: str,
    status: str,
    policy_version: str,
) -> None:
    """Update a legacy receipt or insert one current-generation queue row."""
    context = dict((row or {}).get("category_context") or {})
    object_discovery = not plan["category_codes"]
    context.update({
        "admission_state": "ELIGIBLE",
        "populate_method": policy_version,
        "daily_reconciliation_policy": policy_version,
        "daily_reconciliation_reason": reason,
        "AI_QUEUE_ADMISSION_GATE": "YES" if status == "PRE_RESEARCH_WAITING" else "NO",
        "primary_category": priority.get("queue_primary_category"),
        "category_codes": plan["category_codes"],
        "document_routing_mode": plan.get("document_routing_mode"),
        "requires_object_discovery": object_discovery,
        "initial_priority": "LOW" if object_discovery else "HIGH",
        "research_priority": "LOW" if object_discovery else "HIGH",
    })
    commercial_priority = int(priority.get("queue_commercial_priority_score") or 0)
    fields = {
        "source_table": source["source_table"],
        "source_id": source["source_id"],
        "contract_number": source.get("contract_number"),
        "source_start_date": plan["source_start_date"],
        "queue_lane": (
            "discovery_review"
            if object_discovery
            else "awarded_recent"
            if str(source["source_table"]).endswith("_awarded")
            else "open_active"
        ),
        "priority_score": commercial_priority or (10 if object_discovery else 50),
        "candidate_level": priority.get("queue_medal"),
        "candidate_initial_medal": priority.get("queue_initial_medal"),
        "current_effective_medal": priority.get("queue_current_medal"),
        "category_codes": plan["category_codes"],
        "category_context": psycopg2.extras.Json(context),
        "research_action": "FACTUAL_FEEDER_ADMITTED" if status == "PRE_RESEARCH_WAITING" else "NO_DOCUMENT_RESEARCH",
        "research_depth": "normal" if object_discovery else "highest",
        "research_action_v2": plan["research_action_v2"],
        "plan_version": plan["plan_version"],
        "priority_policy_version": plan["priority_policy_version"],
        "document_plan_version": plan["document_plan_version"],
        "work_tier": int(plan.get("work_tier") or 4),
        "source_lifecycle": plan["source_lifecycle"],
        "project_active": plan["project_active"],
        "project_end_at": plan["project_end_at"],
        "project_remaining_days": plan["project_remaining_days"],
        "execution_phase": plan["execution_phase"],
        "required_facts": psycopg2.extras.Json(plan["required_facts"]),
        "required_document_types": psycopg2.extras.Json(plan["required_document_types"]),
        "selected_source_document_ids": plan["selected_source_document_ids"],
        "selected_physical_keys": plan["selected_physical_keys"],
        "fallback_source_document_ids": plan["fallback_source_document_ids"],
        "soft_fallback_source_document_ids": plan["soft_fallback_source_document_ids"],
        "selected_documents": psycopg2.extras.Json(plan["selected_documents"]),
        "status": status,
        "last_error": (
            None
            if status == "PRE_RESEARCH_WAITING"
            else "NO_DOCUMENT_RESEARCH"
            if status == "SKIPPED_NOT_TARGET"
            else "NO_EXECUTABLE_DOCUMENT_PLAN"
        ),
    }
    names = list(fields)
    values = list(fields.values())
    if row is None:
        names += ["procurement_id", "pipeline_generation"]
        values += [int(source["id"]), generation]
        cur.execute(
            sql.SQL("INSERT INTO document_processing_queue ({}, plan_built_at) VALUES ({}, NOW())").format(
                sql.SQL(", ").join(map(sql.Identifier, names)),
                sql.SQL(", ").join(sql.Placeholder() for _ in names),
            ),
            values,
        )
        return
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder())
        for name in names
    )
    cur.execute(
        sql.SQL(
            "UPDATE document_processing_queue SET {}, "
            "plan_built_at=NOW(), worker_id=NULL, started_at=NULL, "
            "completed_at=NULL, next_attempt_at=NULL, attempt_count=0 "
            "WHERE id=%s AND status IN "
            "('SKIPPED_NOT_TARGET','NO_LINKS','PENDING','PRE_RESEARCH_WAITING')"
        ).format(assignments),
        values + [int(row["id"])],
    )
    if cur.rowcount != 1:
        raise RuntimeError(f"queue row {row['id']} changed during reconciliation")
