"""Daily procurement-level reconciliation for the document queue."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict

import psycopg2
import psycopg2.extras

from src.services.commercial_routing_v3.procurement_queue_priority import (
    aggregate_procurement_opportunities,
)
from src.services.commercial_routing_v3.reconciliation_document_plan import (
    plan_queue_status,
    prepare_document_plans,
)
from src.services.commercial_routing_v3.reconciliation_queue_writer import (
    write_queue_plan,
)


ACTIVE_STATUSES = frozenset({"PENDING", "PRE_RESEARCH_WAITING", "PROCESSING"})
FROZEN_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "SKIPPED_NOISE"})
POLICY_VERSION = "CURRENT_ELIGIBLE_DAILY_V2"
STALE_QUEUE_REASON = "STALE_NOT_CURRENT_ELIGIBLE"
NO_RESEARCH_QUEUE_REASON = "NO_DOCUMENT_RESEARCH"


def _current_eligible_workset(crm_db: Any) -> tuple[dict, dict, dict]:
    rows = crm_db.execute_query(
        """
        SELECT o.procurement_id, o.commercial_category_code,
               o.commercial_category_code AS category_code,
               o.opportunity_track, o.commercial_state,
               o.current_effective_medal, o.candidate_initial_medal,
               o.candidate_medal, o.commercial_priority_score,
               p.id, p.source_table, p.source_id, p.contract_number,
               p.start_date, p.crm_stage, p.award_status, p.source_status,
               p.end_date, p.delivery_start_date, p.delivery_end_date,
               p.execution_start_at, p.execution_end_at
          FROM crm_procurement_category_opportunities o
          JOIN crm_procurement_scope_authority a
            ON a.procurement_id = o.procurement_id
           AND a.admission_state = 'ELIGIBLE'
          JOIN crm_procurements p ON p.id = o.procurement_id
         WHERE o.status = 'CURRENT'
         ORDER BY o.procurement_id, o.id
        """
    ) or []
    priorities = aggregate_procurement_opportunities(rows)
    sources: Dict[int, Dict[str, Any]] = {}
    opportunities: Dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        pid = int(row["procurement_id"])
        opportunities[pid].append(dict(row))
        sources.setdefault(
            pid,
            dict(row),
        )
    return priorities, sources, opportunities


def _queue_lane(source_table: str) -> str:
    return (
        "awarded_recent"
        if str(source_table or "").endswith("_awarded")
        else "open_active"
    )


def _context(
    existing: Any,
    *,
    priority: dict,
    link_count: int,
    reason: str,
) -> dict:
    value = existing if isinstance(existing, dict) else {}
    return {
        **value,
        "admission_state": "ELIGIBLE",
        "populate_method": POLICY_VERSION,
        "daily_reconciliation_policy": POLICY_VERSION,
        "daily_reconciliation_reason": reason,
        "link_count": int(link_count),
        "primary_category": priority.get("queue_primary_category"),
        "category_codes": priority.get("queue_category_codes") or [],
    }


def reconcile_current_eligible_document_queue(
    crm_db: Any,
    *,
    document_db_kwargs: dict,
    pipeline_generation: str,
    apply: bool,
) -> dict:
    """Refresh active rows and restore only current, eligible unfinished work."""
    priorities, sources, opportunities = _current_eligible_workset(crm_db)
    pids = sorted(priorities)
    rows_by_pid: dict[int, list[dict]] = defaultdict(list)
    conn = psycopg2.connect(**document_db_kwargs)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, procurement_id, status, last_error, plan_version,
                       research_action, research_action_v2,
                       selected_source_document_ids,
                       current_effective_medal, candidate_initial_medal,
                       category_codes, category_context
                 FROM document_processing_queue
                 WHERE pipeline_generation = %s
                   AND (
                     procurement_id = ANY(%s)
                     OR status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING')
                   )
                 ORDER BY id
                """,
                (pipeline_generation, pids),
            )
            for row in cur.fetchall():
                rows_by_pid[int(row["procurement_id"])].append(dict(row))

            active_updates = []
            candidates = []
            stale_action_ids = []
            preserved_terminal = 0
            preserved_other_skip = 0
            for pid in pids:
                priority = priorities[pid]
                existing = rows_by_pid.get(pid, [])
                active = [
                    row for row in existing
                    if str(row.get("status") or "").upper() in ACTIVE_STATUSES
                ]
                if len(active) > 1:
                    raise RuntimeError(
                        f"duplicate active document queue rows for procurement {pid}"
                    )
                if active:
                    row = active[0]
                    action_v2 = str(row.get("research_action_v2") or "")
                    if (
                        row["status"] != "PROCESSING"
                        and row.get("plan_version") == "queue_v2"
                        and action_v2
                        not in {
                            "DOCUMENT_RESEARCH_REQUIRED",
                            "DOCUMENT_CONFIRMATION_REQUIRED",
                        }
                    ):
                        stale_action_ids.append(int(row["id"]))
                        continue
                    # Rebuild legacy queue_v2 rows once so the two-contour
                    # routing mode is materialized. Without this condition an
                    # old category-bound plan remains active forever because
                    # it already has selected document IDs.
                    routing_mode = (row.get("category_context") or {}).get(
                        "document_routing_mode"
                    )
                    if (
                        row.get("plan_version") != "queue_v2"
                        or not row.get("selected_source_document_ids")
                        or not routing_mode
                    ) and row["status"] != "PROCESSING":
                        candidates.append((pid, row, "ACTIVE_PLAN_REFRESH"))
                        continue
                    current = priority.get("queue_current_medal")
                    initial = priority.get("queue_initial_medal")
                    categories = priority.get("queue_category_codes") or []
                    if (
                        row.get("current_effective_medal") != current
                        or row.get("candidate_initial_medal") != initial
                        or sorted(row.get("category_codes") or []) != categories
                    ):
                        active_updates.append(
                            (current, initial, categories, int(row["id"]))
                        )
                    continue

                if any(
                    str(row.get("status") or "").upper()
                    in FROZEN_TERMINAL_STATUSES
                    for row in existing
                ):
                    preserved_terminal += 1
                    continue
                legacy = [
                    row for row in existing
                    if str(row.get("status") or "").upper()
                    == "SKIPPED_NOT_TARGET"
                    and str(row.get("last_error") or "").startswith(
                        "legacy_not_admitted"
                    )
                ]
                no_links = [
                    row for row in existing
                    if str(row.get("status") or "").upper() == "NO_LINKS"
                ]
                if legacy:
                    candidates.append((pid, legacy[-1], "LEGACY_READMISSION"))
                elif no_links:
                    candidates.append((pid, no_links[-1], "NO_LINKS_RECHECK"))
                elif not existing:
                    candidates.append((pid, None, "MISSING_CURRENT_GENERATION"))
                else:
                    preserved_other_skip += 1

            plans, link_report = prepare_document_plans(
                cur, generation=pipeline_generation, candidates=candidates,
                sources=sources, opportunities=opportunities, apply=apply,
            )
            transitions = inserts = 0
            missing_source_identity = 0
            planned_waiting = planned_no_links = 0
            for pid, row, reason in candidates:
                source = sources[pid]
                if not source.get("source_table") or source.get("source_id") is None:
                    missing_source_identity += 1
                    continue
                plan = plans.get(pid)
                if plan is None:
                    planned_no_links += 1
                    continue
                status = plan_queue_status(plan)
                if status == "NO_LINKS":
                    planned_no_links += 1
                else:
                    planned_waiting += 1
                if apply:
                    write_queue_plan(
                        cur, row=row, source=source, priority=priorities[pid],
                        plan=plan, generation=pipeline_generation, reason=reason,
                        status=status, policy_version=POLICY_VERSION,
                    )
                    if row is None:
                        inserts += 1
                    else:
                        transitions += 1

            if apply and active_updates:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    UPDATE document_processing_queue
                       SET current_effective_medal=%s,
                           candidate_initial_medal=%s,
                           category_codes=%s
                     WHERE id=%s
                       AND status IN ('PENDING','PRE_RESEARCH_WAITING','PROCESSING')
                    """,
                    active_updates,
                    page_size=500,
                )

            stale_ids = [
                int(row["id"])
                for pid, rows in rows_by_pid.items()
                if pid not in priorities
                for row in rows
                if row["status"] != "PROCESSING"
            ]
            if apply and stale_ids:
                cur.execute(
                    """
                    UPDATE document_processing_queue
                       SET status='SKIPPED_NOT_TARGET',
                           worker_id=NULL,
                           started_at=NULL,
                           completed_at=NOW(),
                           next_attempt_at=NULL,
                           last_error=%s
                     WHERE id = ANY(%s)
                    """,
                    (STALE_QUEUE_REASON, stale_ids),
                )
            if apply and stale_action_ids:
                cur.execute(
                    """
                    UPDATE document_processing_queue
                       SET status='SKIPPED_NOT_TARGET',
                           worker_id=NULL,
                           started_at=NULL,
                           completed_at=NOW(),
                           next_attempt_at=NULL,
                           last_error=%s
                     WHERE id = ANY(%s)
                    """,
                    (NO_RESEARCH_QUEUE_REASON, stale_action_ids),
                )
        conn.commit() if apply else conn.rollback()
        return {
            "pipeline_generation": pipeline_generation,
            "eligible_current_procurements": len(pids),
            "active_rows": sum(
                1
                for rows in rows_by_pid.values()
                for row in rows
                if str(row.get("status") or "").upper() in ACTIVE_STATUSES
            ),
            "planned_stale_retired": len(stale_ids),
            "planned_no_research_retired": len(stale_action_ids),
            "planned_priority_updates": len(active_updates),
            "planned_transitions": sum(row is not None for _, row, _ in candidates),
            "planned_inserts": sum(row is None for _, row, _ in candidates),
            "planned_waiting": planned_waiting,
            "planned_no_links": planned_no_links,
            "preserved_terminal": preserved_terminal,
            "preserved_other_skip": preserved_other_skip,
            "missing_source_identity": missing_source_identity,
            "updated_priority_rows": len(active_updates) if apply else 0,
            "transitioned_rows": transitions,
            "inserted_rows": inserts,
            "retired_stale_rows": len(stale_ids) if apply else 0,
            "retired_no_research_rows": len(stale_action_ids) if apply else 0,
            "writes": apply,
            "policy_version": POLICY_VERSION,
            **link_report,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
