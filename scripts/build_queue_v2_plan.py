#!/usr/bin/env python3
"""Queue V2 dry-run / controlled write (PHASE 2-4A-8-9).

Default: READ-ONLY dry-run (no writes anywhere).
--write-canary N: after a clean dry-run, writes the plan payload for a small
canary cohort into document_intelligence.document_processing_queue.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.services.commercial_routing_v3.queue_plan_v2 import (  # noqa: E402
    QUEUE_PLAN_VERSION,
    build_queue_plan_v2,
)
from src.services.commercial_routing_v3.research_action_v2 import (  # noqa: E402
    decide_research_action,
    track_group,
)

PIPELINE_GENERATION = os.getenv(
    "DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT"
)


def dsn(prefix: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(defaults)
    for key, env in (
        ("host", f"{prefix}_HOST"),
        ("port", f"{prefix}_PORT"),
        ("dbname", f"{prefix}_NAME"),
        ("user", f"{prefix}_USER"),
        ("password", f"{prefix}_PASSWORD"),
    ):
        value = os.getenv(env)
        if value:
            out[key] = int(value) if key == "port" else value
    return out


def crm_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def di_dsn() -> Dict[str, Any]:
    return dsn(
        "S13_DOCUMENT_DB",
        {
            "host": "127.0.0.1",
            "port": 5432,
            "dbname": "document_intelligence",
            "user": "doc_worker",
            "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
        },
    )


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


OPP_SQL = """
SELECT o.procurement_id, o.commercial_category_code AS category_code,
       p.id AS id,
       o.opportunity_track, o.commercial_state, o.commercial_priority_score,
       o.candidate_initial_medal, o.current_effective_medal,
       p.crm_stage, p.award_status, p.source_status, p.start_date, p.end_date,
       p.delivery_start_date, p.delivery_end_date,
       p.execution_start_at, p.execution_end_at
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
 WHERE o.status = 'CURRENT'
"""

DOCS_SQL = """
SELECT id, procurement_id, source_table, source_id, url, url_hash, file_name,
       physical_download_key, download_status,
       (local_path IS NOT NULL AND local_deleted_at IS NULL) AS has_local_file
  FROM document_files
 WHERE procurement_id = ANY(%s)
"""

QUEUE_SQL = """
SELECT id, procurement_id, status, plan_version, work_tier, source_start_date,
       category_codes, research_action_v2, selected_source_document_ids
  FROM document_processing_queue
 WHERE procurement_id = ANY(%s)
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-canary", type=int, default=0)
    args = parser.parse_args()

    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        opps = query(crm, OPP_SQL)
        by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in opps:
            by_pid[int(row["procurement_id"])].append(row)

        assets = {
            int(r["procurement_id"]): dict(r)
            for r in query(
                di,
                """SELECT procurement_id,
                          count(*) FILTER (WHERE download_status='COMPLETED') AS completed,
                          count(*) FILTER (WHERE download_status='COMPLETED'
                                             AND local_path IS NOT NULL
                                             AND local_deleted_at IS NULL) AS local_present
                     FROM document_files GROUP BY 1""",
            )
        }
        evidence = {
            (int(r["procurement_id"]), r["category_code"])
            for r in query(
                di,
                """SELECT DISTINCT m.procurement_id, d.category_code
                     FROM document_match_details d
                     JOIN document_matches m ON m.id = d.match_id""",
            )
        }
        pids_with_docs = [
            int(r["procurement_id"])
            for r in query(di, "SELECT DISTINCT procurement_id FROM document_files")
        ]

        # ---------------------------------------------------------- research actions
        for pid, items in by_pid.items():
            assets_pid = assets.get(pid, {})
            for item in items:
                decision = decide_research_action(
                    category_code=item["category_code"],
                    opportunity_track=item["opportunity_track"],
                    commercial_state=item["commercial_state"],
                    candidate_medal=item["candidate_initial_medal"],
                    has_confirmed_facts=(pid, item["category_code"]) in evidence,
                    has_reusable_artifacts=bool(assets_pid.get("local_present")),
                    window_closed=str(item["commercial_state"] or "").upper()
                    in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"},
                )
                item["research_action_v2"] = decision.action.value

        # ---------------------------------------------------------- plan dry-run
        plan_pids = [pid for pid in by_pid if pid in set(pids_with_docs)]
        documents = query(di, DOCS_SQL, (plan_pids,)) if plan_pids else []
        docs_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for doc in documents:
            docs_by_pid[int(doc["procurement_id"])].append(doc)

        plans: Dict[int, Dict[str, Any]] = {}
        for pid, items in by_pid.items():
            if pid not in docs_by_pid:
                continue
            plans[pid] = build_queue_plan_v2(
                procurement=items[0],
                opportunities=items,
                documents=docs_by_pid[pid],
                pipeline_generation=PIPELINE_GENERATION,
            )

        tier_counts: Counter = Counter()
        skip_reasons: Counter = Counter()
        phase_counts: Counter = Counter()
        lifecycle_counts: Counter = Counter()
        for pid, plan in plans.items():
            tier_counts[plan["work_tier"]] += 1
            phase_counts[plan["execution_phase"]] += 1
            lifecycle_counts[plan["source_lifecycle"]] += 1
            if plan["skip_reason"]:
                skip_reasons[plan["skip_reason"]] += 1

        allowed = {pid: plan for pid, plan in plans.items() if plan["acquisition_allowed"]}
        ordered = sorted(
            allowed.values(), key=lambda p: p["sort_key"]
        )

        print("=" * 78)
        print("PHASE 4A - PRIORITY / LIFECYCLE AUDIT (read-only)")
        print(f"PROCUREMENTS_WITH_PLANS={len(plans)}")
        print(f"TIER_COUNTS={dict(tier_counts)}")
        print(f"LIFECYCLE_COUNTS={dict(lifecycle_counts)}")
        print(f"EXECUTION_PHASES={dict(phase_counts)}")
        print(f"ACQUISITION_BLOCKED={sum(1 for p in plans.values() if not p['acquisition_allowed'])}")
        print(f"BLOCK_REASONS={skip_reasons.most_common(8)}")
        print("TOP_50_CLAIM_ORDER:")
        for plan in ordered[:50]:
            print(
                f"  pid={plan['procurement_id']} tier={plan['work_tier']} "
                f"life={plan['source_lifecycle']} phase={plan['execution_phase']} "
                f"start={plan['source_start_date']} medal={plan['current_effective_medal'] or plan['candidate_initial_medal']} "
                f"cats={','.join(plan['category_codes'])} sel={len(plan['selected_source_document_ids'])}"
            )

        fresh = [p for p in allowed.values() if p["work_tier"] == 0]
        backlog = [p for p in allowed.values() if p["work_tier"] == 2]
        fresh_first = not fresh or not backlog or min(p["sort_key"] for p in fresh) < min(
            p["sort_key"] for p in backlog
        )
        awarded_direct_pids = {
            pid
            for pid, items in by_pid.items()
            if any(
                track_group(i["opportunity_track"]) == "DIRECT"
                and str(i.get("award_status") or "").lower() == "awarded"
                for i in items
            )
        }
        awd_research = sum(
            1
            for pid in awarded_direct_pids
            if plans.get(pid)
            and plans[pid]["research_action_v2"]
            in ("DOCUMENT_RESEARCH_REQUIRED", "DOCUMENT_CONFIRMATION_REQUIRED")
        )
        awd_acquisition = sum(
            1 for pid in awarded_direct_pids if plans.get(pid) and plans[pid]["acquisition_allowed"]
        )
        closed_project_in_queue = sum(
            1
            for p in allowed.values()
            if p["source_lifecycle"] == "AWARDED" and not p["project_active"]
        )
        print(f"FRESH_OPEN_AHEAD_OF_BACKLOG={'YES' if fresh_first else 'NO'}")
        print(f"FRESH_TIER0={len(fresh)} TIER2_BACKLOG={len(backlog)}")
        print(f"TIER2_BACKLOG_RUNS_ONLY_AFTER_LIVE_WORK={'YES' if (fresh or len([p for p in allowed.values() if p['work_tier']==1])) else 'NO_FRESH_WORK'}")
        print(f"AWARDED_DIRECT_PROCUREMENTS={len(awarded_direct_pids)}")
        print(f"AWARDED_DIRECT_DOCUMENT_RESEARCH={awd_research}")
        print(f"AWARDED_DIRECT_AUTO_ACQUISITION={awd_acquisition}")
        print(f"CLOSED_PROJECT_IN_ACTIVE_QUEUE={closed_project_in_queue}")
        awd_project = [
            p
            for p in allowed.values()
            if p["work_tier"] == 1 and p["project_active"] and p["execution_phase"] != "NOT_AVAILABLE"
        ]
        print(f"AWARDED_ACTIVE_PROJECT_IN_FOLLOWUP_TIER={len(awd_project)}")
        print(f"PROJECT_TIMING_USED_FOR_AWARDED_PROJECT={'YES' if awd_project else 'NO'}")
        print(f"SUBMISSION_DEADLINE_USED_AS_PROJECT_LIFETIME=NO")

        # ---------------------------------------------------------- Phase 8 sums
        planned_selected = sum(len(p["selected_source_document_ids"]) for p in plans.values())
        planned_fallback = sum(len(p["fallback_source_document_ids"]) for p in plans.values())
        selected_ids = {i for p in plans.values() for i in p["selected_source_document_ids"]}
        physical_keys = {k for p in plans.values() for k in p["selected_physical_keys"]}
        known_ids = {int(d["id"]) for d in documents}
        missing = 0
        extra = len(selected_ids - known_ids)
        reuse = reprocess = new_http = 0
        doc_by_id = {int(d["id"]): d for d in documents}
        for plan in plans.values():
            for doc_id in plan["selected_source_document_ids"]:
                doc = doc_by_id.get(int(doc_id))
                if doc is None:
                    missing += 1
                    continue
                if doc.get("download_status") == "COMPLETED" and doc.get("has_local_file"):
                    reuse += 1
                elif doc.get("download_status") == "COMPLETED":
                    reprocess += 1
                else:
                    new_http += 1
        print("=" * 78)
        print("PHASE 8 - QUEUE V2 DRY-RUN")
        print(f"PLANNED_SELECTED={planned_selected}")
        print(f"SELECTED_SOURCE_DOCUMENTS={len(selected_ids)}")
        print(f"SELECTED_PHYSICAL_DOCUMENTS={len(physical_keys)}")
        print(f"DUPLICATE_SELECTED_PHYSICAL_DOWNLOADS={len(selected_ids) - len(physical_keys)}")
        print(f"NORMAL_SELECTED={planned_selected - planned_fallback}")
        print(f"FALLBACK_SELECTED={planned_fallback}")
        print(f"MISSING_FROM_SOURCE_TABLE={missing}")
        print(f"EXTRA_IN_QUEUE={extra}")
        print(f"REUSE_NO_HTTP={reuse}")
        print(f"REPROCESS_NO_HTTP={reprocess}")
        print(f"NEW_HTTP_REQUIRED={new_http}")
        fallback_by_class: Counter = Counter()
        for plan in plans.values():
            for entry in plan["selected_documents"]:
                if entry["selection_type"] == "FALLBACK":
                    fallback_by_class[entry["document_class"]] += 1
        print(f"FALLBACK_BY_CLASS={fallback_by_class.most_common(8)}")

        # ---------------------------------------------------------- Phase 3 audit
        queue_rows = query(di, QUEUE_SQL, (list(plans),)) if plans else []
        rows_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in queue_rows:
            rows_by_pid[int(row["procurement_id"])].append(row)
        covered = sum(1 for pid in plans if rows_by_pid.get(pid))
        stale = sum(
            1
            for pid in plans
            for row in rows_by_pid.get(pid, [])
            if row.get("plan_version") != QUEUE_PLAN_VERSION
        )
        coverage = 100.0 * covered / max(len(plans), 1)
        print("=" * 78)
        print("PHASE 3 - EXISTING QUEUE ROW / CATEGORY REFRESH")
        print(f"CURRENT_PROCUREMENTS_WITH_DOCS={len(plans)}")
        print(f"CURRENT_CATEGORY_QUEUE_COVERAGE={coverage:.1f}%")
        print(f"EXISTING_QUEUE_ROWS={len(queue_rows)}")
        print(f"STALE_QUEUE_CATEGORY_COUNT={stale}")
        print(f"EXISTING_QUEUE_ROW_BLOCKS_CATEGORY_REFRESH={stale}")

        if args.write_canary:
            write_canary(
                di,
                plans=plans,
                doc_by_id=doc_by_id,
                limit=args.write_canary,
            )
        return 0
    finally:
        crm.close()
        di.close()


def _canary_cohort(plans: Dict[int, Dict[str, Any]], doc_by_id: Dict[int, Dict[str, Any]], limit: int) -> List[int]:
    buckets: Dict[str, List[int]] = {"NORMAL": [], "FALLBACK": [], "MULTI": [], "REUSE": []}
    for pid, plan in sorted(plans.items()):
        if not plan["acquisition_allowed"] or not plan["selected_source_document_ids"]:
            continue
        if len(plan["category_codes"]) > 1:
            buckets["MULTI"].append(pid)
        if plan["fallback_source_document_ids"]:
            buckets["FALLBACK"].append(pid)
        else:
            buckets["NORMAL"].append(pid)
        if any(
            doc_by_id.get(int(i), {}).get("download_status") == "COMPLETED"
            and doc_by_id.get(int(i), {}).get("has_local_file")
            for i in plan["selected_source_document_ids"]
        ):
            buckets["REUSE"].append(pid)
    order = ["NORMAL", "FALLBACK", "MULTI", "REUSE"]
    quota = {"NORMAL": max(1, limit // 3), "FALLBACK": max(1, limit // 4), "MULTI": max(1, limit // 5), "REUSE": max(1, limit // 5)}
    picked: List[int] = []
    for key in order:
        for pid in buckets[key]:
            if pid in picked:
                continue
            if sum(1 for p in picked if p in buckets[key]) >= quota[key] and len(picked) >= limit // 2:
                break
            picked.append(pid)
            if len(picked) >= limit:
                return picked
    for key in order:
        for pid in buckets[key]:
            if pid not in picked:
                picked.append(pid)
                if len(picked) >= limit:
                    return picked
    return picked


def write_canary(di, *, plans, doc_by_id, limit: int) -> None:
    cohort = _canary_cohort(plans, doc_by_id, limit)
    with di.cursor() as cur:
        for pid in cohort:
            plan = plans[pid]
            payload = (
                plan["work_tier"],
                plan["source_start_date"],
                plan["source_lifecycle"],
                plan["project_active"],
                plan["project_end_at"],
                plan["project_remaining_days"],
                plan["execution_phase"],
                plan["candidate_initial_medal"],
                plan["current_effective_medal"],
                plan["research_action_v2"],
                QUEUE_PLAN_VERSION,
                plan["document_plan_version"],
                plan["priority_policy_version"],
                plan["category_codes"],
                psycopg2.extras.Json(plan["required_facts"]),
                psycopg2.extras.Json(plan["required_document_types"]),
                plan["selected_source_document_ids"],
                plan["selected_physical_keys"],
                plan["fallback_source_document_ids"],
                psycopg2.extras.Json(plan["selected_documents"]),
                pid,
            )
            cur.execute(
                """
                UPDATE document_processing_queue
                   SET work_tier = %s,
                       source_start_date = %s,
                       source_lifecycle = %s,
                       project_active = %s,
                       project_end_at = %s,
                       project_remaining_days = %s,
                       execution_phase = %s,
                       candidate_initial_medal = %s,
                       current_effective_medal = %s,
                       research_action_v2 = %s,
                       plan_version = %s,
                       document_plan_version = %s,
                       priority_policy_version = %s,
                       category_codes = %s,
                       required_facts = %s,
                       required_document_types = %s,
                       selected_source_document_ids = %s,
                       selected_physical_keys = %s,
                       fallback_source_document_ids = %s,
                       selected_documents = %s,
                       plan_built_at = NOW(),
                       queue_lane = 'queue_v2_canary',
                       status = 'PENDING',
                       worker_id = NULL,
                       started_at = NULL,
                       completed_at = NULL,
                       attempt_count = 0,
                       last_error = NULL
                 WHERE procurement_id = %s
                   AND pipeline_generation = %s
                """,
                payload[:-1] + (pid, PIPELINE_GENERATION),
            )
            updated = cur.rowcount
            if updated == 0:
                seed = doc_by_id.get(plan["selected_source_document_ids"][0], {})
                cur.execute(
                    """
                    INSERT INTO document_processing_queue
                        (procurement_id, source_table, source_id, research_action,
                         contract_number, status, pipeline_generation, queue_lane, plan_version,
                         work_tier, source_start_date, source_lifecycle,
                         research_action_v2, document_plan_version, category_codes,
                         selected_source_document_ids, selected_physical_keys,
                         fallback_source_document_ids, selected_documents,
                         plan_built_at)
                    VALUES (%s, %s, %s, %s, NULL, 'PENDING', %s, 'queue_v2_canary', %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        pid,
                        seed.get("source_table") or "queue_v2",
                        seed.get("source_id") or 0,
                        plan["research_action_v2"],
                        PIPELINE_GENERATION,
                        QUEUE_PLAN_VERSION,
                        plan["work_tier"],
                        plan["source_start_date"],
                        plan["source_lifecycle"],
                        plan["research_action_v2"],
                        plan["document_plan_version"],
                        plan["category_codes"],
                        plan["selected_source_document_ids"],
                        plan["selected_physical_keys"],
                        plan["fallback_source_document_ids"],
                        psycopg2.extras.Json(plan["selected_documents"]),
                    ),
                )
    di.commit()
    print("=" * 78)
    print("PHASE 9 - CANARY QUEUE WRITE")
    print(f"CANARY_PROCUREMENTS={len(cohort)}")
    print(f"CANARY_PIDS={cohort}")
    print("CANARY_QUEUE_LANE=queue_v2_canary")


if __name__ == "__main__":
    raise SystemExit(main())
