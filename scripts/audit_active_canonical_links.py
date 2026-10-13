#!/usr/bin/env python3
"""READ-ONLY audit: active procurements whose canonical S7 links exist but
document_files is empty (ACTIVE_CANONICAL_LINK_INGEST_V1, step 1-2).

Uses the existing canonical resolver:
    src/services/commercial_routing_v3/document_links.py
identity: contract_number first, fallback source_id. No new resolver.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from src.services.commercial_routing_v3.document_links import (  # noqa: E402
    batch_count_document_links,
)

CANARY_PROCUREMENT_ID = int(os.getenv("CANARY_PROCUREMENT_ID", "946"))
CANARY_CONTRACT = os.getenv("CANARY_CONTRACT", "0310200000326002743")


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


def active_procurements(crm):
    cur = crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT p.id, p.source_table, p.source_id, p.contract_number,
               sa.source_lifecycle,
               CASE
                 WHEN sa.source_lifecycle = 'OPEN' THEN 'A_OPEN_CURRENT'
                 ELSE 'A_AWARDED_OBJECT'
               END AS bucket
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
         WHERE (sa.source_lifecycle = 'OPEN' AND o.procurement_id IS NOT NULL)
            OR (sa.source_lifecycle = 'AWARDED'
                AND (coalesce(o.any_object, false) OR coalesce(o.any_followup, false)))
        """
    )
    return [dict(r) for r in cur.fetchall()]


def document_file_counts(di, ids):
    out = {}
    cur = di.cursor()
    for start in range(0, len(ids), 5000):
        chunk = ids[start:start + 5000]
        cur.execute(
            "SELECT procurement_id, count(*) FROM document_files"
            " WHERE procurement_id = ANY(%s) GROUP BY 1",
            (chunk,),
        )
        for pid, n in cur.fetchall():
            out[int(pid)] = int(n)
    return out


def main() -> int:
    crm = crm_conn()
    di = di_conn()
    try:
        procs = active_procurements(crm)
        link_counts = batch_count_document_links(procs)
        doc_counts = document_file_counts(di, [int(p["id"]) for p in procs])

        total = len(procs)
        with_links = 0
        with_docs = 0
        links_no_docs = 0
        missing_rows = 0
        by_bucket = {}
        offenders = []
        for p in procs:
            pid = int(p["id"])
            links = int(link_counts.get(pid) or 0)
            docs = int(doc_counts.get(pid) or 0)
            b = p["bucket"]
            by_bucket.setdefault(b, {"procs": 0, "with_links": 0, "with_docs": 0,
                                     "links_no_docs": 0, "missing_link_rows": 0})
            by_bucket[b]["procs"] += 1
            if links > 0:
                with_links += 1
                by_bucket[b]["with_links"] += 1
            if docs > 0:
                with_docs += 1
                by_bucket[b]["with_docs"] += 1
            if links > 0 and docs == 0:
                links_no_docs += 1
                missing_rows += links
                by_bucket[b]["links_no_docs"] += 1
                by_bucket[b]["missing_link_rows"] += links
                offenders.append({
                    "procurement_id": pid,
                    "contract_number": p.get("contract_number"),
                    "source_table": p.get("source_table"),
                    "bucket": b,
                    "canonical_links": links,
                })

        canary = None
        for p in procs:
            if int(p["id"]) == CANARY_PROCUREMENT_ID or str(p.get("contract_number")) == CANARY_CONTRACT:
                canary = {
                    "procurement_id": int(p["id"]),
                    "contract_number": p.get("contract_number"),
                    "canonical_links": int(link_counts.get(int(p["id"])) or 0),
                    "document_files": int(doc_counts.get(int(p["id"])) or 0),
                }
                break

        report = {
            "ACTIVE_PROCUREMENTS": total,
            "WITH_CANONICAL_LINKS": with_links,
            "WITH_DOCUMENT_FILES": with_docs,
            "LINKS_EXIST_BUT_DOCUMENT_FILES_ZERO": links_no_docs,
            "TOTAL_MISSING_LINK_ROWS": missing_rows,
            "BY_BUCKET": by_bucket,
            "CANARY": canary,
            "OFFENDERS_SAMPLE": sorted(offenders, key=lambda x: -x["canonical_links"])[:20],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
