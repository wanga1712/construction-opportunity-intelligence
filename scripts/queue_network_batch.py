#!/usr/bin/env python3
"""Queue one tier's REDOWNLOAD set into a dedicated lane (targeted downloader).

Only V3-selected documents whose local artifact is NOT present are enqueued, so
every HTTP target is an explicitly planned document (HTTP_TO_UNSELECTED=0).
No CRM/medal writes; queue writes are limited to the tier lane.
"""

from __future__ import annotations

import argparse
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

from src.services.commercial_routing_v3.queue_plan_v2 import QUEUE_PLAN_VERSION, build_queue_plan_v2  # noqa: E402
from src.services.commercial_routing_v3.research_action_v2 import decide_research_action  # noqa: E402

PIPELINE_GENERATION = os.getenv("DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT")

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
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"), "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"), "password": os.getenv("CRM_DB_PASSWORD", ""),
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
       p.id AS id, p.crm_stage, p.award_status, p.source_status,
       p.start_date, p.end_date, p.delivery_start_date, p.delivery_end_date,
       p.execution_start_at, p.execution_end_at
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
 WHERE o.status = 'CURRENT'
"""

DOCS_SQL = """
SELECT id, procurement_id, source_table, source_id, url, url_hash, file_name,
       physical_download_key, download_status, local_path, local_deleted_at,
       file_size_bytes
  FROM document_files WHERE procurement_id = ANY(%s)
"""


def local_present(doc: Dict[str, Any], cache: Dict[str, bool]) -> bool:
    if doc.get("local_deleted_at") is not None or not doc.get("local_path"):
        return False
    key = str(doc["local_path"])
    if key in cache:
        return cache[key]
    p = Path(key)
    ok = p.exists() and p.is_file()
    if ok:
        expected = _MAGIC.get(p.suffix.lower())
        if expected:
            try:
                with p.open("rb") as fh:
                    head = fh.read(8)
                ok = any(head.startswith(sig) for sig in expected)
            except Exception:
                ok = False
    cache[key] = ok
    return ok


_ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z", ".001", ".002", ".003", ".004", ".007")


def artifact_class(doc: Dict[str, Any]) -> str:
    """fast (bulk) | heavy (archives >5MB, pdf >20MB)."""
    name = str(doc.get("file_name") or "").lower()
    size = int(doc.get("file_size_bytes") or 0)
    if name.endswith(_ARCHIVE_SUFFIXES) and size > 5 * 1024 * 1024:
        return "heavy"
    if name.endswith(".pdf") and size > 20 * 1024 * 1024:
        return "heavy"
    return "fast"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, required=True)
    parser.add_argument("--lane", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-plans", type=int, default=0)
    parser.add_argument("--require-ext", default="")
    parser.add_argument("--require-name-substr", default="")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--artifact-class", default="", choices=["", "fast", "heavy"],
                        help="restrict to fast (bulk) or heavy (big archives/pdf) artifacts")
    args = parser.parse_args()
    lane = args.lane or f"queue_v2_tier{args.tier}"

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
        pids_with_docs = {int(r["procurement_id"]) for r in query(di, "SELECT DISTINCT procurement_id FROM document_files")}
        for pid, items in by_pid.items():
            apid = assets.get(pid, {})
            for item in items:
                d = decide_research_action(
                    category_code=item["category_code"], opportunity_track=item["opportunity_track"],
                    commercial_state=item["commercial_state"], candidate_medal=item["candidate_initial_medal"],
                    has_confirmed_facts=(pid, item["category_code"]) in evidence,
                    has_reusable_artifacts=bool(apid.get("local_present")),
                    window_closed=str(item["commercial_state"] or "").upper() in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"},
                )
                item["research_action_v2"] = d.action.value

        plan_pids = [pid for pid in by_pid if pid in pids_with_docs]
        documents = query(di, DOCS_SQL, (plan_pids,)) if plan_pids else []
        docs_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for doc in documents:
            docs_by_pid[int(doc["procurement_id"])].append(doc)
        doc_by_id = {int(d["id"]): d for d in documents}

        cache: Dict[str, bool] = {}
        rows: List[Tuple[int, Dict[str, Any], List[Dict[str, Any]]]] = []
        counters = Counter()
        for pid, items in by_pid.items():
            if pid not in docs_by_pid:
                continue
            if args.pid and pid != args.pid:
                continue
            plan = build_queue_plan_v2(procurement=items[0], opportunities=items,
                                       documents=docs_by_pid[pid], pipeline_generation=PIPELINE_GENERATION)
            if not plan["acquisition_allowed"] or plan["work_tier"] != args.tier:
                continue
            # Never enqueue a plan the queue claim filter would reject
            # (policy leak: batch input must equal claimable work).
            if plan["research_action_v2"] not in (
                "DOCUMENT_RESEARCH_REQUIRED",
                "DOCUMENT_CONFIRMATION_REQUIRED",
            ):
                counters["SKIPPED_NOT_CLAIMABLE"] += 1
                continue
            pending = []
            for entry in plan["selected_documents"]:
                sid = entry.get("source_document_id")
                if sid is None:
                    continue
                doc = doc_by_id.get(int(sid))
                if doc is None or local_present(doc, cache):
                    continue
                if args.artifact_class and artifact_class(doc) != args.artifact_class:
                    continue
                pending.append(entry)
            counters["TIER_PLANS"] += 1
            if not pending:
                counters["PLANS_NO_HTTP"] += 1
                continue
            pending_ids = [int(e["source_document_id"]) for e in pending]
            plan = dict(plan)
            plan["selected_source_document_ids"] = pending_ids
            plan["fallback_source_document_ids"] = [
                i for i in pending_ids if i in set(plan["fallback_source_document_ids"])
            ]
            plan["soft_fallback_source_document_ids"] = [
                i for i in pending_ids if i in set(plan["soft_fallback_source_document_ids"])
            ]
            plan["selected_documents"] = pending
            plan["selected_physical_keys"] = [
                doc_by_id[i].get("physical_download_key") or doc_by_id[i].get("url_hash") or doc_by_id[i].get("url")
                for i in pending_ids if i in doc_by_id
            ]
            if args.require_ext and not any(
                str(doc_by_id[int(e["source_document_id"])].get("file_name", "")).lower().endswith(
                    "." + args.require_ext.lower()
                )
                for e in pending if int(e["source_document_id"]) in doc_by_id
            ):
                counters["SKIPPED_EXT_FILTER"] += 1
                continue
            if args.require_name_substr and not any(
                args.require_name_substr.lower() in str(doc_by_id[int(e["source_document_id"])].get("file_name", "")).lower()
                for e in pending if int(e["source_document_id"]) in doc_by_id
            ):
                counters["SKIPPED_NAME_FILTER"] += 1
                continue
            rows.append((pid, plan, pending))
            counters["TIER_INPUT"] += len(pending_ids)
            counters["TIER_PLANS_WITH_HTTP"] += 1
            if args.max_plans and len(rows) >= args.max_plans:
                break

        print(f"TIER={args.tier} LANE={lane}")
        print(f"TIER_PLANS={counters['TIER_PLANS']}")
        print(f"TIER_PLANS_WITH_HTTP={counters['TIER_PLANS_WITH_HTTP']}")
        print(f"TIER_PLANS_NO_HTTP={counters['PLANS_NO_HTTP']}")
        print(f"TIER_PLANS_NOT_CLAIMABLE={counters['SKIPPED_NOT_CLAIMABLE']}")
        print(f"TIER_INPUT={counters['TIER_INPUT']}")
        print(f"TIER_INPUT_CLAIMABLE={counters['TIER_INPUT']}")

        if args.dry_run:
            print("DRY_RUN=YES (no queue writes)")
            return 0

        with di.cursor() as cur:
            for pid, plan, _pending in rows:
                payload = (
                    plan["work_tier"], plan["source_start_date"], plan["source_lifecycle"],
                    plan["project_active"], plan["project_end_at"], plan["project_remaining_days"],
                    plan["execution_phase"], plan["candidate_initial_medal"], plan["current_effective_medal"],
                    plan["research_action_v2"], QUEUE_PLAN_VERSION, plan["document_plan_version"],
                    plan["priority_policy_version"], plan["category_codes"],
                    psycopg2.extras.Json(plan["required_facts"]),
                    psycopg2.extras.Json(plan["required_document_types"]),
                    plan["selected_source_document_ids"], plan["selected_physical_keys"],
                    plan["fallback_source_document_ids"], plan["soft_fallback_source_document_ids"],
                    psycopg2.extras.Json(plan["selected_documents"]),
                )
                cur.execute(
                    """
                    UPDATE document_processing_queue
                       SET work_tier=%s, source_start_date=%s, source_lifecycle=%s, project_active=%s,
                           project_end_at=%s, project_remaining_days=%s, execution_phase=%s,
                           candidate_initial_medal=%s, current_effective_medal=%s, research_action_v2=%s,
                           plan_version=%s, document_plan_version=%s, priority_policy_version=%s,
                           category_codes=%s, required_facts=%s, required_document_types=%s,
                           selected_source_document_ids=%s, selected_physical_keys=%s,
                           fallback_source_document_ids=%s, soft_fallback_source_document_ids=%s,
                           selected_documents=%s, plan_built_at=NOW(), queue_lane=%s, status='PENDING',
                           worker_id=NULL, started_at=NULL, completed_at=NULL, attempt_count=0, last_error=NULL
                     WHERE procurement_id=%s AND pipeline_generation=%s
                    """,
                    payload + (lane, pid, PIPELINE_GENERATION),
                )
                if cur.rowcount == 0:
                    seed = doc_by_id[plan["selected_source_document_ids"][0]]
                    cur.execute(
                        """
                        INSERT INTO document_processing_queue
                            (procurement_id, source_table, source_id, research_action, contract_number,
                             status, pipeline_generation, queue_lane, plan_version, work_tier,
                             source_start_date, source_lifecycle, research_action_v2, document_plan_version,
                             category_codes, selected_source_document_ids, selected_physical_keys,
                             fallback_source_document_ids, soft_fallback_source_document_ids,
                             selected_documents, plan_built_at)
                        VALUES (%s,%s,%s,%s,NULL,'PENDING',%s,%s,%s,
                                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        """,
                        (pid, seed.get("source_table") or "queue_v2", seed.get("source_id") or 0,
                         plan["research_action_v2"], PIPELINE_GENERATION, lane, QUEUE_PLAN_VERSION,
                         plan["work_tier"], plan["source_start_date"], plan["source_lifecycle"],
                         plan["research_action_v2"], plan["document_plan_version"], plan["category_codes"],
                         plan["selected_source_document_ids"], plan["selected_physical_keys"],
                         plan["fallback_source_document_ids"], plan["soft_fallback_source_document_ids"],
                         psycopg2.extras.Json(plan["selected_documents"])),
                    )
        di.commit()
        print(f"QUEUE_WRITTEN={len(rows)} lane={lane}")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
