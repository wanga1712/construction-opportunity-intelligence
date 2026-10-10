#!/usr/bin/env python3
"""Queue V2 canary verification (PHASE 10-11). Read-only reporting."""

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

CANARY_LANE = "queue_v2_canary"


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=180, help="canary window")
    args = parser.parse_args()
    di = psycopg2.connect(**di_dsn())
    try:
        rows = query(
            di,
            f"""
            SELECT id, procurement_id, status, work_tier, source_lifecycle,
                   execution_phase, research_action_v2,
                   COALESCE(array_length(selected_source_document_ids,1),0) AS sel,
                   COALESCE(array_length(fallback_source_document_ids,1),0) AS fb,
                   selected_documents
              FROM document_processing_queue
             WHERE queue_lane = %s
             ORDER BY id
            """,
            (CANARY_LANE,),
        )
        pids = sorted({int(r["procurement_id"]) for r in rows})
        selected_ids = {
            int(i)
            for r in query(
                di,
                "SELECT selected_source_document_ids FROM document_processing_queue WHERE queue_lane=%s",
                (CANARY_LANE,),
            )
            for i in (r["selected_source_document_ids"] or [])
        }
        print("=" * 78)
        print("PHASE 10 - CANARY PLAN / QUEUE")
        print(f"CANARY_QUEUE_ROWS={len(rows)}")
        print(f"CANARY_PROCUREMENTS={len(pids)}")
        print(f"CANARY_STATUS={dict(Counter(r['status'] for r in rows))}")
        print(f"SELECTED_SOURCE_DOCUMENTS={len(selected_ids)}")
        fallback_ids = {
            int(i)
            for r in query(
                di,
                "SELECT fallback_source_document_ids FROM document_processing_queue WHERE queue_lane=%s",
                (CANARY_LANE,),
            )
            for i in (r["fallback_source_document_ids"] or [])
        }
        print(f"NORMAL_SELECTED={len(selected_ids) - len(fallback_ids)}")
        print(f"FALLBACK_SELECTED={len(fallback_ids)}")

        if not pids:
            return 0

        requests = query(
            di,
            """
            SELECT id, requested_at, http_status, url, bytes_received, error_class,
                   concurrency_at_start, xid, retry_after, request_type
              FROM eis_request_events
             WHERE requested_at > now() - (%s || ' minutes')::interval
             ORDER BY requested_at
            """,
            (args.minutes,),
        )
        probes = [r for r in requests if r["request_type"] == "PROBE"]
        requests = [r for r in requests if r["request_type"] != "PROBE"]
        files = query(
            di,
            """
            SELECT id, procurement_id, url_hash, physical_download_key, file_name,
                   download_status, file_size_bytes, downloaded_at, local_path IS NOT NULL AS has_local
              FROM document_files
             WHERE procurement_id = ANY(%s)
               AND COALESCE(downloaded_at, created_at) > now() - (%s || ' minutes')::interval
            """,
            (pids, args.minutes),
        )
        print("=" * 78)
        print("PHASE 10 - NETWORK CANARY")
        print(f"HTTP_REQUESTS={len(requests)}")
        print(f"PROBE_REQUESTS_EXCLUDED={len(probes)}")
        print(f"PROBE_STATUS={dict(Counter(r['http_status'] for r in probes))}")
        print(f"HTTP_STATUS={dict(Counter(r['http_status'] for r in requests))}")
        print(f"HTTP_ERROR_CLASSES={dict(Counter(r['error_class'] for r in requests if r['error_class']))}")
        print(f"HTTP_BYTES={sum(int(r['bytes_received'] or 0) for r in requests)}")
        print(f"MAX_CONCURRENCY_AT_START={max([int(r['concurrency_at_start'] or 0) for r in requests], default=0)}")
        selected_keys = {
            _phys_key(r["url"] if r.get("url") else r.get("key"))
            for r in query(
                di,
                """SELECT url, COALESCE(physical_download_key, url_hash) AS key
                     FROM document_files WHERE id = ANY(%s)""",
                (sorted(selected_ids),),
            )
            if selected_ids
        }
        unselected = [r for r in requests if _phys_key(r["url"]) not in selected_keys]
        print(f"HTTP_TO_UNSELECTED_DOCUMENT={len(unselected)}")
        if unselected:
            print(f"  UNSELECTED_EXAMPLES={[r['url'][:80] for r in unselected[:5]]}")
        phys = Counter(_phys_key(r["url"]) for r in requests)
        dup = {k: v for k, v in phys.items() if v > 1}
        print(f"DUPLICATE_PHYSICAL_HTTP={sum(v - 1 for v in dup.values())}")
        status_404 = [r for r in requests if r["http_status"] in (404, 410)]
        print(f"404_410_REQUESTS={len(status_404)}")
        print(f"429_EVENTS={sum(1 for r in requests if r['http_status'] == 429)}")
        print(f"FILES_ROWS_IN_WINDOW={len(files)}")
        print(f"FILES_STATUS={dict(Counter(f['download_status'] for f in files))}")

        touched_ids = {int(f["id"]) for f in files}
        print(f"SELECTED_DOC_ROWS_TOUCHED={len(touched_ids & selected_ids)}")
        print(f"UNSELECTED_DOC_ROWS_TOUCHED={len(touched_ids - selected_ids)}")

        # ---------------------------------------------------------- facts (Phase 11)
        matches = query(
            di,
            """
            SELECT m.procurement_id, d.category_code, m.document_name, count(*) AS n
              FROM document_matches m
              JOIN document_match_details d ON d.match_id = m.id
             WHERE m.procurement_id = ANY(%s)
               AND m.created_at > now() - (%s || ' minutes')::interval
             GROUP BY 1, 2, 3
            """,
            (pids, args.minutes),
        )
        entities = query(
            di,
            """
            SELECT procurement_id, category_code,
                   count(*) AS entities,
                   count(*) FILTER (WHERE quantity_value IS NOT NULL) AS with_quantity,
                   count(*) FILTER (WHERE quantity_unit_normalized IS NOT NULL) AS with_unit,
                   count(*) FILTER (WHERE product_name_normalized IS NOT NULL) AS with_product,
                   count(*) FILTER (WHERE total_price_value IS NOT NULL) AS with_total_price
              FROM structured_entities
             WHERE procurement_id = ANY(%s)
               AND created_at > now() - (%s || ' minutes')::interval
             GROUP BY 1, 2
            """,
            (pids, args.minutes),
        )
        results = query(
            di,
            """
            SELECT procurement_id, status, count(*) AS n, sum(matches_found) AS matches_found
              FROM document_processing_results
             WHERE procurement_id = ANY(%s)
               AND COALESCE(completed_at, created_at) > now() - (%s || ' minutes')::interval
             GROUP BY 1, 2
            """,
            (pids, args.minutes),
        )
        print("=" * 78)
        print("PHASE 11 - PARSER / NORMALIZER RESULT")
        print(f"PARSED_PROCUREMENTS={len({r['procurement_id'] for r in results})}")
        print(f"RESULTS_BY_STATUS={dict(Counter(r['status'] for r in results))}")
        print(f"MATCHED_PROCUREMENTS={len({m['procurement_id'] for m in matches})}")
        print(f"MATCH_ROWS={sum(int(m['n']) for m in matches)}")
        print(f"MATCH_CATEGORIES={dict(Counter(m['category_code'] for m in matches))}")
        print(f"STRUCTURED_PROCUREMENTS={len({e['procurement_id'] for e in entities})}")
        print(f"STRUCTURED_ENTITIES={sum(int(e['entities']) for e in entities)}")
        print(f"ENTITY_WITH_QUANTITY={sum(int(e['with_quantity']) for e in entities)}")
        print(f"ENTITY_WITH_UNIT={sum(int(e['with_unit']) for e in entities)}")
        print(f"ENTITY_WITH_PRODUCT={sum(int(e['with_product']) for e in entities)}")
        print(f"ENTITY_WITH_TOTAL_PRICE={sum(int(e['with_total_price']) for e in entities)}")
        print(
            "DIRECT_PARSED="
            f"{len({r['procurement_id'] for r in results if r['procurement_id'] in pids})}"
        )
        if entities:
            print("ENTITY_BY_CATEGORY:")
            for e in sorted(entities, key=lambda x: -int(x["entities"]))[:10]:
                print(
                    f"  {e['category_code']}: entities={e['entities']} "
                    f"qty={e['with_quantity']} unit={e['with_unit']} "
                    f"product={e['with_product']} total={e['with_total_price']}"
                )
        return 0
    finally:
        di.close()


def _phys_key(url: Optional[str]) -> str:
    return (url or "").split("?")[0].rstrip("/").lower()


if __name__ == "__main__":
    raise SystemExit(main())
