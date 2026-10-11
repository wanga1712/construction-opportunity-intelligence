#!/usr/bin/env python3
"""HISTORICAL ADMISSION / DOCUMENT_PLAN_V3 - READ-ONLY measurement.

Re-runs the whole base through today's rules without any write or HTTP:

    all procurements -> lifecycle -> category admission -> track
    -> research_action -> DOCUMENT_SELECTION_V3 plan -> selected documents
    -> classify LOCAL artifact state

The OLD download_status is never authority: a document is only "reprocessable"
if the NEW plan selects it AND its local artifact is really present.
"""

from __future__ import annotations

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
    ".rtf": (b"{\\rtf",),
    ".txt": (),
    ".csv": (),
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
       o.status AS opportunity_status,
       o.opportunity_track, o.commercial_state, o.commercial_priority_score,
       o.candidate_initial_medal, o.current_effective_medal,
       o.expected_category_value, o.category_value_basis,
       p.id AS id, p.crm_stage, p.award_status, p.source_status,
       p.start_date, p.end_date, p.delivery_start_date, p.delivery_end_date,
       p.execution_start_at, p.execution_end_at
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
"""

DOCS_SQL = """
SELECT id, procurement_id, source_table, source_id, url, url_hash, file_name,
       physical_download_key, download_status, local_path, local_deleted_at,
       (local_path IS NOT NULL AND local_deleted_at IS NULL) AS has_local_file
  FROM document_files
 WHERE procurement_id = ANY(%s)
"""


def local_state(doc: Dict[str, Any], cache: Dict[str, str]) -> str:
    """PRESENT | MISSING | DELETED | CORRUPT (old download_status is ignored)."""
    if doc.get("local_deleted_at") is not None:
        return "DELETED"
    path = doc.get("local_path")
    if not path:
        return "MISSING"
    key = str(path)
    if key in cache:
        return cache[key]
    p = Path(path)
    if not p.exists() or not p.is_file():
        cache[key] = "MISSING"
        return "MISSING"
    suffix = p.suffix.lower()
    expected = _MAGIC.get(suffix)
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


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        total_procurements = query(crm, "SELECT count(*) AS c FROM crm_procurements")[0]["c"]
        opps = query(crm, OPP_SQL)
        by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in opps:
            by_pid[int(row["procurement_id"])].append(row)

        current_opps = [r for r in opps if (r.get("opportunity_status") or "") == "CURRENT"]
        superseded = len(opps) - len(current_opps)
        current_pids = sorted({int(r["procurement_id"]) for r in current_opps})
        tracks_all = Counter()
        for r in current_opps:
            tracks_all[track_group(r["opportunity_track"])] += 1

        assets = {
            int(r["procurement_id"]): dict(r)
            for r in query(
                di,
                "SELECT procurement_id,"
                " count(*) FILTER (WHERE download_status='COMPLETED') AS completed,"
                " count(*) FILTER (WHERE download_status='COMPLETED' AND local_path IS NOT NULL"
                "                    AND local_deleted_at IS NULL) AS local_present"
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

        counts = Counter()
        tracks = Counter()
        tier_by_bucket: Dict[str, Counter] = defaultdict(Counter)
        local_cache: Dict[str, str] = {}
        selected_ids_total = 0
        tier_counts = Counter()
        selected_physical: set = set()

        for pid, items in by_pid.items():
            if pid not in docs_by_pid:
                continue
            if not any((i.get("opportunity_status") or "") == "CURRENT" for i in items):
                continue
            current_items = [i for i in items if (i.get("opportunity_status") or "") == "CURRENT"]
            plan = build_queue_plan_v2(
                procurement=current_items[0],
                opportunities=current_items,
                documents=docs_by_pid[pid],
                pipeline_generation=PIPELINE_GENERATION,
            )
            counts["DOCUMENT_PLANS_TOTAL"] += 1
            for item in current_items:
                tracks[track_group(item["opportunity_track"])] += 1
            action = plan["research_action_v2"]
            tier = plan["work_tier"]
            if action == "NO_OPPORTUNITY":
                counts["NO_OPPORTUNITY"] += 1
                continue
            if not plan["selected_source_document_ids"]:
                counts["NO_DOCUMENT_RESEARCH"] += 1
                continue
            for doc_id in plan["selected_source_document_ids"]:
                selected_ids_total += 1
                doc = doc_by_id.get(int(doc_id))
                if doc is None:
                    counts["SELECTED_DOC_NOT_RESOLVABLE"] += 1
                    continue
                selected_physical.add(
                    doc.get("physical_download_key")
                    or doc.get("url_hash")
                    or (doc.get("url") or "").strip().lower()
                    or f"row:{doc_id}"
                )
                state = local_state(doc, local_cache)
                counts[f"SELECTED_LOCAL_{state}"] += 1
                if state == "PRESENT":
                    counts["REPROCESS_NO_HTTP"] += 1
                else:
                    counts["REDOWNLOAD_REQUIRED"] += 1
                    tier_by_bucket["REDOWNLOAD_REQUIRED"][f"TIER_{tier}"] += 1
                tier_counts[f"TIER_{tier}"] += 1

        print("=" * 78)
        print("HISTORICAL ADMISSION / DOCUMENT_PLAN_V3 - READ-ONLY")
        print(f"PROCUREMENTS_TOTAL={total_procurements}")
        print(f"PROCUREMENTS_WITH_OPPORTUNITIES={len(by_pid)}")
        print(f"CURRENT_PROCUREMENTS={len(current_pids)}")
        print(f"CURRENT_OPPORTUNITIES={len(current_opps)}")
        print(f"SUPERSEDED_CANDIDATES={superseded}")
        print(
            f"TRACKS_CURRENT={{'DIRECT': {tracks[GROUP_DIRECT]}, "
            f"'EMBEDDED': {tracks[GROUP_EMBEDDED]}, 'DESIGN': {tracks[GROUP_DESIGN]}, "
            f"'UNKNOWN': {tracks[GROUP_UNKNOWN]}}}"
        )
        print(
            f"TRACKS_CURRENT_OPPORTUNITIES={{'DIRECT': {tracks_all[GROUP_DIRECT]}, "
            f"'EMBEDDED': {tracks_all[GROUP_EMBEDDED]}, 'DESIGN': {tracks_all[GROUP_DESIGN]}, "
            f"'UNKNOWN': {tracks_all[GROUP_UNKNOWN]}}}"
        )
        print(f"DOCUMENT_PLANS_TOTAL={counts['DOCUMENT_PLANS_TOTAL']}")
        print(f"SELECTED_DOCUMENTS_TOTAL={selected_ids_total}")
        print(f"UNIQUE_PHYSICAL_SELECTED={len(selected_physical)}")
        print(f"NO_OPPORTUNITY={counts['NO_OPPORTUNITY']}")
        print(f"NO_DOCUMENT_RESEARCH={counts['NO_DOCUMENT_RESEARCH']}")
        print("-" * 78)
        print(f"SELECTED_LOCAL_PRESENT={counts['SELECTED_LOCAL_PRESENT']}")
        print(f"SELECTED_LOCAL_MISSING={counts['SELECTED_LOCAL_MISSING']}")
        print(f"SELECTED_LOCAL_DELETED={counts['SELECTED_LOCAL_DELETED']}")
        print(f"SELECTED_LOCAL_CORRUPT={counts['SELECTED_LOCAL_CORRUPT']}")
        print(f"SELECTED_DOC_NOT_RESOLVABLE={counts['SELECTED_DOC_NOT_RESOLVABLE']}")
        print("-" * 78)
        print(f"REPROCESS_NO_HTTP={counts['REPROCESS_NO_HTTP']}")
        print(f"REDOWNLOAD_REQUIRED={counts['REDOWNLOAD_REQUIRED']}")
        print(f"REDOWNLOAD_BY_TIER={dict(tier_by_bucket['REDOWNLOAD_REQUIRED'])}")
        print(f"SELECTED_BY_TIER={dict(tier_counts)}")
        print(f"LOCAL_PRESENT={counts['SELECTED_LOCAL_PRESENT']}")
        print(f"LOCAL_MISSING={counts['SELECTED_LOCAL_MISSING']}")
        print(f"LOCAL_DELETED={counts['SELECTED_LOCAL_DELETED']}")
        print(f"LOCAL_CORRUPT={counts['SELECTED_LOCAL_CORRUPT']}")
        classified = sum(
            counts[k]
            for k in (
                "SELECTED_LOCAL_PRESENT",
                "SELECTED_LOCAL_MISSING",
                "SELECTED_LOCAL_DELETED",
                "SELECTED_LOCAL_CORRUPT",
            )
        )
        pct = 100.0 * classified / selected_ids_total if selected_ids_total else 100.0
        print(f"SELECTED_DOCUMENTS_CLASSIFIED_BY_LOCAL_STATE={pct:.1f}%")
        current_with_docs = [p for p in current_pids if p in pids_with_docs]
        cov = 100.0 * counts["DOCUMENT_PLANS_TOTAL"] / len(current_with_docs) if current_with_docs else 100.0
        print(f"CURRENT_PROCUREMENTS_WITH_DOCS={len(current_with_docs)}")
        print(f"CURRENT_CATEGORY_COVERAGE={cov:.1f}%")
        print(f"OLD_COMPLETED_USED_AS_AUTHORITY=NO")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
