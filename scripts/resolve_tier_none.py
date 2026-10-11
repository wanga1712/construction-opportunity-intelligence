#!/usr/bin/env python3
"""TIER_NONE_RESOLUTION - READ-ONLY.

Every V3 plan with work_tier = NULL must either get an explicit tier (0/1/2) or
be explicitly excluded from acquisition. Nothing may stay NULL yet remain
network-claimable. Also recomputes the final network volume.
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.services.commercial_routing_v3.queue_plan_v2 import build_queue_plan_v2  # noqa: E402
from src.services.commercial_routing_v3.research_action_v2 import (  # noqa: E402
    GROUP_DESIGN,
    GROUP_DIRECT,
    GROUP_EMBEDDED,
    GROUP_UNKNOWN,
    decide_research_action,
    track_group,
)

PIPELINE_GENERATION = os.getenv("DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT")

NO_ACQUISITION = "NO_ACQUISITION"
BLOCKED = "BLOCKED_REVIEW"

_MAGIC = {
    ".pdf": (b"%PDF",),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".xlsx": (b"PK\x03\x04",),
    ".xlsm": (b"PK\x03\x04",),
    ".odt": (b"PK\x03\x04",),
    ".zip": (b"PK\x03\x04",),
    ".rar": (b"Rar!",),
    ".7z": (b"7z\xbc\xaf",),
    ".doc": (b"\xd0\xcf\x11\xe0",),
    ".xls": (b"\xd0\xcf\x11\xe0",),
}


def crm_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


OPP_SQL = """
SELECT o.procurement_id, o.commercial_category_code AS category_code,
       o.status AS opportunity_status, o.opportunity_track, o.commercial_state,
       o.commercial_priority_score, o.candidate_initial_medal, o.current_effective_medal,
       p.id AS id, p.crm_stage, p.award_status, p.source_status, p.object_type,
       p.start_date, p.end_date, p.delivery_start_date, p.delivery_end_date,
       p.execution_start_at, p.execution_end_at
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
 WHERE o.status = 'CURRENT'
"""

DOCS_SQL = """
SELECT id, procurement_id, file_name, url, url_hash, physical_download_key,
       download_status, local_path, local_deleted_at
  FROM document_files WHERE procurement_id = ANY(%s)
"""


def local_state(doc: Dict[str, Any], cache: Dict[str, str]) -> str:
    if doc.get("local_deleted_at") is not None:
        return "DELETED"
    if not doc.get("local_path"):
        return "MISSING"
    key = str(doc["local_path"])
    if key in cache:
        return cache[key]
    p = Path(key)
    if not p.exists() or not p.is_file():
        cache[key] = "MISSING"
        return "MISSING"
    expected = _MAGIC.get(p.suffix.lower())
    if expected:
        try:
            with p.open("rb") as fh:
                head = fh.read(8)
            if not any(head.startswith(sig) for sig in expected):
                cache[key] = "CORRUPT"
                return "CORRUPT"
        except Exception:
            cache[key] = "CORRUPT"
            return "CORRUPT"
    cache[key] = "PRESENT"
    return "PRESENT"


def bucket_and_proposal(plan: Dict[str, Any], item: Dict[str, Any]) -> Tuple[str, str]:
    """(bucket, proposed_tier) for a work_tier=NULL plan."""
    group = track_group(item["opportunity_track"])
    lifecycle = (plan.get("source_lifecycle") or "UNKNOWN").upper()
    reason = plan.get("skip_reason") or "TIER_NONE_UNEXPLAINED"
    active = bool(plan.get("project_active"))
    has_start = bool(item.get("start_date"))
    has_scope = bool(item.get("object_type"))

    # explicit no-acquisition reasons produced by the priority policy
    if reason in {
        "DIRECT_AWARDED_WINDOW_CLOSED",
    }:
        return "AWARDED_DIRECT", NO_ACQUISITION
    if reason == "DIRECT_SUBMISSION_CLOSED":
        # submission window closed, award not assigned yet - not acquirable
        return "DIRECT_SUBMISSION_CLOSED", NO_ACQUISITION
    if reason == "DIRECT_TERMINAL":
        return "STALE_SOURCE", NO_ACQUISITION
    if reason == "PROJECT_TERMINAL":
        return "AWARDED_CLOSED_PROJECT", NO_ACQUISITION
    if reason == "PROJECT_CLOSED_NO_EXECUTION_WINDOW":
        return "AWARDED_CLOSED_PROJECT", NO_ACQUISITION
    if reason == "UNKNOWN_TRACK_AWARDED_NO_EXECUTION_WINDOW":
        return "AWARDED_CLOSED_PROJECT", NO_ACQUISITION
    if reason == "UNKNOWN_TRACK_TERMINAL":
        return "STALE_SOURCE", NO_ACQUISITION

    if lifecycle == "TERMINAL":
        return "STALE_SOURCE", NO_ACQUISITION
    if lifecycle == "OPEN":
        if not has_start:
            return "OPEN_WITHOUT_START_DATE", BLOCKED
        return "OPEN_WITH_START_DATE", "0"
    if lifecycle in {"AWARDED", "SUBMISSION_CLOSED"}:
        if group == GROUP_DIRECT:
            return "AWARDED_DIRECT", NO_ACQUISITION
        if group in (GROUP_EMBEDDED, GROUP_DESIGN):
            if active:
                return "AWARDED_ACTIVE_PROJECT", "1"
            return "AWARDED_CLOSED_PROJECT", NO_ACQUISITION
        return "OTHER", BLOCKED
    if lifecycle == "UNKNOWN":
        if not has_scope:
            return "MISSING_SCOPE", BLOCKED
        if not has_start:
            return "MISSING_TIMING", BLOCKED
        return "UNKNOWN_LIFECYCLE", BLOCKED
    if not has_start and not item.get("end_date"):
        return "MISSING_TIMING", BLOCKED
    return "OTHER", "2"


def main() -> int:
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
                "SELECT procurement_id, count(*) FILTER (WHERE download_status='COMPLETED'"
                " AND local_path IS NOT NULL AND local_deleted_at IS NULL) AS local_present"
                " FROM document_files GROUP BY 1",
            )
        }
        evidence = {
            (int(r["procurement_id"]), r["category_code"])
            for r in query(
                di,
                "SELECT DISTINCT m.procurement_id, d.category_code"
                " FROM document_match_details d JOIN document_matches m ON m.id=d.match_id",
            )
        }
        pids_with_docs = {
            int(r["procurement_id"])
            for r in query(di, "SELECT DISTINCT procurement_id FROM document_files")
        }
        for pid, items in by_pid.items():
            apid = assets.get(pid, {})
            for item in items:
                decision = decide_research_action(
                    category_code=item["category_code"],
                    opportunity_track=item["opportunity_track"],
                    commercial_state=item["commercial_state"],
                    candidate_medal=item["candidate_initial_medal"],
                    has_confirmed_facts=(pid, item["category_code"]) in evidence,
                    has_reusable_artifacts=bool(apid.get("local_present")),
                    window_closed=str(item["commercial_state"] or "").upper()
                    in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"},
                )
                item["research_action_v2"] = decision.action.value

        plan_pids = [pid for pid in by_pid if pid in pids_with_docs]
        documents = query(di, DOCS_SQL, (plan_pids,)) if plan_pids else []
        docs_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for doc in documents:
            docs_by_pid[int(doc["procurement_id"])].append(doc)
        doc_by_id = {int(d["id"]): d for d in documents}

        cache: Dict[str, str] = {}
        buckets = Counter()
        proposals = Counter()
        reasons = Counter()
        rows_out: List[str] = []
        final = Counter()
        final_tier = Counter()

        for pid, items in by_pid.items():
            if pid not in docs_by_pid:
                continue
            plan = build_queue_plan_v2(
                procurement=items[0], opportunities=items,
                documents=docs_by_pid[pid], pipeline_generation=PIPELINE_GENERATION,
            )
            tier = plan.get("work_tier")
            allowed = bool(plan.get("acquisition_allowed"))
            if tier is None:
                buckets["TIER_NONE_BEFORE"] += 1
                item = items[0]
                bucket, proposed = bucket_and_proposal(plan, item)
                buckets[bucket] += 1
                proposals[proposed] += 1
                reasons[plan.get("skip_reason") or "NONE"] += 1
                rows_out.append(
                    f"PID={pid} cat={item['category_code']} track={track_group(item['opportunity_track'])} "
                    f"lifecycle={plan.get('source_lifecycle')} scope={item.get('object_type')} "
                    f"start={item.get('start_date')} deadline={item.get('end_date')} "
                    f"project_active={plan.get('project_active')} "
                    f"p_start={item.get('delivery_start_date') or item.get('execution_start_at')} "
                    f"p_end={item.get('delivery_end_date') or item.get('execution_end_at')} "
                    f"action={plan.get('research_action_v2')} medal={plan.get('current_effective_medal')} "
                    f"reason_tier_none={plan.get('skip_reason')} bucket={bucket} proposed_tier={proposed}"
                )
                if plan.get("research_action_v2") in {
                    "DOCUMENT_RESEARCH_REQUIRED",
                    "DOCUMENT_CONFIRMATION_REQUIRED",
                }:
                    buckets["NULL_TIER_CLAIMABLE"] += 1
                continue
            if not allowed:
                continue
            final["ACQUIRABLE_PLANS"] += 1
            final_tier[f"TIER_{tier}"] += 1
            for doc_id in plan.get("selected_source_document_ids") or []:
                doc = doc_by_id.get(int(doc_id))
                if doc is None:
                    continue
                state = local_state(doc, cache)
                final["SELECTED"] += 1
                if state == "PRESENT":
                    final["REPROCESS_NO_HTTP"] += 1
                else:
                    final["REDOWNLOAD_REQUIRED_FINAL"] += 1
                    final_tier[f"REDOWNLOAD_TIER_{tier}"] += 1
                final[f"LOCAL_{state}"] += 1

        print("=" * 78)
        print("TIER_NONE_RESOLUTION - READ-ONLY")
        print(f"TIER_NONE_BEFORE={buckets['TIER_NONE_BEFORE']}")
        for key in (
            "OPEN_WITH_START_DATE",
            "OPEN_WITHOUT_START_DATE",
            "DIRECT_SUBMISSION_CLOSED",
            "AWARDED_DIRECT",
            "AWARDED_ACTIVE_PROJECT",
            "AWARDED_CLOSED_PROJECT",
            "STALE_SOURCE",
            "UNKNOWN_LIFECYCLE",
            "MISSING_SCOPE",
            "MISSING_TIMING",
            "OTHER",
        ):
            print(f"{key}={buckets.get(key, 0)}")
        claimable_none = sum(1 for p in proposals.values() if p in {"0", "1", "2"})
        print(f"TIER_NONE_AFTER={claimable_none}")
        print(f"TIER_NONE_AFTER_CLAIMABLE={claimable_none}")
        print(f"NULL_TIER_CLAIMABLE={buckets.get('NULL_TIER_CLAIMABLE', 0)}")
        print(f"BLOCKED_WITH_EXPLICIT_REASON={proposals.get(BLOCKED, 0)}")
        print(f"PROPOSED={dict(proposals)}")
        print(f"REASON_TIER_NONE={dict(reasons)}")
        print("-" * 78)
        print("TIER_NONE_ROWS_BEGIN")
        for line in rows_out:
            print(line)
        print("TIER_NONE_ROWS_END")
        print("-" * 78)
        print("FINAL NETWORK VOLUME (acquisition_allowed only)")
        print(f"REDOWNLOAD_REQUIRED_FINAL={final['REDOWNLOAD_REQUIRED_FINAL']}")
        print(f"REPROCESS_NO_HTTP={final['REPROCESS_NO_HTTP']}")
        print(f"SELECTED_DOCUMENTS={final['SELECTED']}")
        print(f"TIER0={final_tier['REDOWNLOAD_TIER_0']}")
        print(f"TIER1={final_tier['REDOWNLOAD_TIER_1']}")
        print(f"TIER2={final_tier['REDOWNLOAD_TIER_2']}")
        print(f"ACQUIRABLE_PLANS={final['ACQUIRABLE_PLANS']}")
        print(f"BLOCKED={proposals.get(BLOCKED, 0)}")
        print(f"NO_ACQUISITION={proposals.get(NO_ACQUISITION, 0)}")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
