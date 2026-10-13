#!/usr/bin/env python3
"""ACTIVE_CANONICAL_LINK_INGEST_V1 — idempotent materialization of canonical S7
document links into document_files for ACTIVE procurements only.

  canonical link (src/services/commercial_routing_v3/document_links.py)
        -> document_files row

Dedup identity: (procurement_id, physical_download_key) — a re-run never creates
duplicates. Worker skip-list is applied (researchable links only).
Only A_OPEN_CURRENT / A_AWARDED_OBJECT. Never B/C.

Default is dry-run; pass --write to insert. Scope with --procurement-id N (repeatable)
or --all-active.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from src.services.commercial_routing_v3.document_links import (  # noqa: E402
    _should_skip_document_name,
    resolve_document_links,
)

PIPELINE_GENERATION = os.getenv(
    "DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT"
)


def crm_conn():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    return psycopg2.connect(**require_crm_db_connect_kwargs())


def di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


ACTIVE_SQL = """
    SELECT p.id, p.source_table, p.source_id, p.contract_number
      FROM crm_procurements p
      JOIN crm_procurement_scope_authority sa ON sa.procurement_id = p.id
      LEFT JOIN (
            SELECT procurement_id,
                   bool_or(opportunity_track IN
                     ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT','DESIGN_INFLUENCE')) AS any_object,
                   bool_or(commercial_state = 'FOLLOW_UP_AWARDED') AS any_followup
              FROM crm_procurement_category_opportunities
             WHERE status = 'CURRENT'
             GROUP BY 1) o ON o.procurement_id = p.id
     WHERE (
            (sa.source_lifecycle = 'OPEN' AND o.procurement_id IS NOT NULL)
         OR (sa.source_lifecycle = 'AWARDED'
             AND (coalesce(o.any_object, false) OR coalesce(o.any_followup, false)))
     )
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--procurement-id", type=int, action="append", default=[])
    ap.add_argument("--all-active", action="store_true")
    args = ap.parse_args()

    if not args.procurement_id and not args.all_active:
        ap.error("give --procurement-id N (repeatable) or --all-active")

    crm = crm_conn()
    di = di_conn()
    try:
        cur = crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if args.procurement_id:
            cur.execute(ACTIVE_SQL + " AND p.id = ANY(%s)", (args.procurement_id,))
        else:
            cur.execute(ACTIVE_SQL)
        procs = [dict(r) for r in cur.fetchall()]

        total_links = 0
        inserted = 0
        existing = 0
        per_proc = []
        dcur = di.cursor()
        for p in procs:
            resolved = resolve_document_links(
                source_table=p["source_table"],
                source_id=p.get("source_id"),
                contract_number=p.get("contract_number"),
                limit=10000,
            )
            rows = []
            seen = set()
            for link in resolved.get("links") or []:
                if _should_skip_document_name(link.get("document_name")):
                    continue
                key = link.get("physical_download_key") or link.get("document_url")
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append(link)
            total_links += len(rows)
            proc_inserted = 0
            for link in rows:
                url = link.get("document_url")
                if not url:
                    continue
                pkey = str(link.get("physical_download_key") or url)
                dcur.execute(
                    "SELECT 1 FROM document_files WHERE procurement_id=%s"
                    " AND physical_download_key=%s LIMIT 1",
                    (int(p["id"]), pkey),
                )
                if dcur.fetchone():
                    existing += 1
                    continue
                if args.write:
                    dcur.execute(
                        """INSERT INTO document_files
                             (procurement_id, source_table, source_id, url, url_hash, file_name,
                              download_status, pipeline_generation, canonical_source_document_id,
                              physical_download_key, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,'PENDING',%s,%s,%s,NOW())""",
                        (
                            int(p["id"]), p["source_table"], p.get("source_id"), url,
                            hashlib.md5(url.encode("utf-8")).hexdigest(),
                            link.get("document_name") or "document",
                            PIPELINE_GENERATION,
                            link.get("source_document_id"),
                            pkey,
                        ),
                    )
                    inserted += 1
                    proc_inserted += 1
            di.commit()
            per_proc.append({
                "procurement_id": int(p["id"]),
                "contract_number": p.get("contract_number"),
                "canonical_links": len(rows),
                "inserted": proc_inserted,
                "resolution_method": resolved.get("resolution_method"),
                "error": resolved.get("error"),
            })

        report = {
            "write": bool(args.write),
            "procurements": len(procs),
            "canonical_links": total_links,
            "inserted": inserted,
            "already_present": existing,
            "pipeline_generation": PIPELINE_GENERATION,
            "per_procurement": per_proc[:20],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
