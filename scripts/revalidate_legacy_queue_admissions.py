#!/usr/bin/env python3
"""Deterministic revalidation for legacy FACTUAL_FEEDER_ADMITTED queue rows.

Read-only by default. --apply writes only category_context markers:
  legacy_revalidation_status = CURRENTLY_ELIGIBLE | LEGACY_HOLD

No Qwen calls, no downloads, no document_files status changes.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _doc_dsn() -> dict:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def _crm_dsn() -> dict:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def _rows(cur) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def load_legacy_rows(doc_conn, limit: Optional[int]) -> List[Dict[str, Any]]:
    sql = """
        SELECT id, procurement_id, contract_number, source_table,
               research_action, category_context, created_at
          FROM document_processing_queue
         WHERE status IN ('PENDING', 'PRE_RESEARCH_WAITING')
           AND category_context->>'legacy_revalidation_status' = 'REQUIRED'
         ORDER BY id
    """
    params: Tuple[Any, ...] = ()
    if limit:
        sql += " LIMIT %s"
        params = (limit,)
    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return _rows(cur)


def load_crm_maps(crm_conn, procurement_ids: List[int]) -> dict:
    if not procurement_ids:
        return {"authority": {}, "procurement": {}, "opportunity": {}, "files": {}}
    with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT procurement_id, admission_state, admission_reason,
                   source_lifecycle, procurement_scope_type,
                   admission_policy_version, updated_at
              FROM crm_procurement_scope_authority
             WHERE procurement_id = ANY(%s)
            """,
            (procurement_ids,),
        )
        authority = {r["procurement_id"]: r for r in _rows(cur)}

        cur.execute(
            """
            SELECT id, contract_number, source_table, crm_stage,
                   start_date, end_date
              FROM crm_procurements
             WHERE id = ANY(%s)
            """,
            (procurement_ids,),
        )
        procurement = {r["id"]: r for r in _rows(cur)}

        cur.execute(
            """
            SELECT procurement_id,
                   count(*) FILTER (WHERE status = 'CURRENT') AS current_count,
                   count(*) FILTER (
                       WHERE status = 'CURRENT'
                         AND commercial_state NOT IN ('ABSENT', 'UNLIKELY')
                         AND COALESCE(jsonb_array_length(positive_evidence), 0) > 0
                   ) AS positive_count,
                   max(current_effective_at) AS last_effective_at
              FROM crm_procurement_category_opportunities
             WHERE procurement_id = ANY(%s)
             GROUP BY procurement_id
            """,
            (procurement_ids,),
        )
        opportunity = {r["procurement_id"]: r for r in _rows(cur)}
    return {
        "authority": authority,
        "procurement": procurement,
        "opportunity": opportunity,
    }


def load_usable_files(doc_conn, procurement_ids: List[int]) -> Dict[int, int]:
    if not procurement_ids:
        return {}
    with doc_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT procurement_id,
                   count(*) FILTER (
                       WHERE download_status = 'COMPLETED'
                         AND local_path IS NOT NULL
                         AND local_deleted_at IS NULL
                   ) AS usable
              FROM document_files
             WHERE procurement_id = ANY(%s)
             GROUP BY procurement_id
            """,
            (procurement_ids,),
        )
        return {r["procurement_id"]: int(r["usable"] or 0) for r in _rows(cur)}


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def classify(row: Dict[str, Any], maps: dict, usable_files: int) -> Dict[str, Any]:
    pid = row["procurement_id"]
    auth = maps["authority"].get(pid) or {}
    proc = maps["procurement"].get(pid) or {}
    opp = maps["opportunity"].get(pid) or {}
    reasons: List[str] = []
    today = date.today()

    admission_state = str(auth.get("admission_state") or "").upper()
    lifecycle = str(auth.get("source_lifecycle") or "").upper()
    scope = str(auth.get("procurement_scope_type") or proc.get("crm_stage") or "").upper()
    end_date = _as_date(proc.get("end_date"))
    positive_count = int(opp.get("positive_count") or 0)

    if not auth:
        reasons.append("AUTHORITY_MISSING")
    elif admission_state != "ELIGIBLE":
        reasons.append(f"AUTHORITY_{admission_state or 'UNKNOWN'}")

    if lifecycle in {"TERMINAL_NO_RESULT", "WAITING_SOURCE_OUTCOME"}:
        reasons.append(f"LIFECYCLE_{lifecycle}")

    if scope == "DIRECT_GOODS":
        if end_date is None or end_date < today + timedelta(days=2):
            reasons.append("DIRECT_SUBMISSION_WINDOW_DEPLETED")
    elif scope in {"WORKS_WITH_EMBEDDED_PRODUCTS", "PROJECT", "DESIGN"}:
        if end_date is not None and end_date < today:
            reasons.append("PROJECT_ENDED")

    if positive_count <= 0:
        reasons.append("NO_POSITIVE_CATEGORY_SIGNAL")

    status = "CURRENTLY_ELIGIBLE" if not reasons else "LEGACY_HOLD"
    if status == "CURRENTLY_ELIGIBLE" and usable_files > 0:
        reasons.append("EXISTING_USABLE_LOCAL_DOCUMENT")
    return {
        "status": status,
        "reasons": reasons,
        "scope": scope or None,
        "lifecycle": lifecycle or None,
        "end_date": end_date.isoformat() if end_date else None,
        "positive_count": positive_count,
        "usable_files": usable_files,
    }


def apply_markers(doc_conn, decisions: List[Tuple[int, Dict[str, Any]]]) -> int:
    updated = 0
    with doc_conn.cursor() as cur:
        for queue_id, decision in decisions:
            cur.execute(
                """
                UPDATE document_processing_queue
                   SET category_context =
                       COALESCE(category_context, '{}'::jsonb)
                       || jsonb_build_object(
                            'legacy_revalidation_status', %s,
                            'legacy_revalidation_reason', %s,
                            'legacy_revalidated_at', NOW()::text
                          )
                 WHERE id = %s
                """,
                (
                    decision["status"],
                    ",".join(decision["reasons"]) or "CURRENT_POLICY_MATCH",
                    queue_id,
                ),
            )
            updated += cur.rowcount
    doc_conn.commit()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    doc_conn = psycopg2.connect(**_doc_dsn())
    crm_conn = psycopg2.connect(**_crm_dsn())
    try:
        rows = load_legacy_rows(doc_conn, args.limit or None)
        pids = sorted({int(r["procurement_id"]) for r in rows if r.get("procurement_id")})
        maps = load_crm_maps(crm_conn, pids)
        usable = load_usable_files(doc_conn, pids)
        decisions = [
            (int(r["id"]), classify(r, maps, usable.get(int(r["procurement_id"]), 0)))
            for r in rows
        ]
        eligible = sum(1 for _, d in decisions if d["status"] == "CURRENTLY_ELIGIBLE")
        hold = len(decisions) - eligible
        print(f"LEGACY_ROWS={len(decisions)}")
        print(f"CURRENTLY_ELIGIBLE={eligible}")
        print(f"LEGACY_HOLD={hold}")
        for queue_id, decision in decisions:
            row = next(r for r in rows if int(r["id"]) == queue_id)
            print(
                "|".join(
                    [
                        str(queue_id),
                        str(row.get("procurement_id")),
                        str(row.get("contract_number") or ""),
                        decision["status"],
                        ",".join(decision["reasons"]) or "CURRENT_POLICY_MATCH",
                        str(decision["scope"] or ""),
                        str(decision["lifecycle"] or ""),
                        str(decision["end_date"] or ""),
                        str(decision["positive_count"]),
                        str(decision["usable_files"]),
                    ]
                )
            )
        if args.apply:
            updated = apply_markers(doc_conn, decisions)
            print(f"APPLIED={updated}")
    finally:
        doc_conn.close()
        crm_conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
