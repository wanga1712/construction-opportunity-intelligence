#!/usr/bin/env python3
"""Cleanup structured_entities: keep only registry-matched GOODS rows."""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2
import psycopg2.extras

for path in ("/opt/CRM_Streamlit", "/opt/tender_documents_research"):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.services.works_vs_goods_service import classify_fact_kind  # noqa: E402
from document_processor.parse_extractors import _resolve_embedded_category  # noqa: E402


def _di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.dry_run == args.apply:
        ap.error("choose --dry-run or --apply")

    conn = _di_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = """
                SELECT id, category_code, entity_type, product_name_raw,
                       product_name_normalized, quantity_value,
                       quantity_unit_normalized
                  FROM structured_entities
                 ORDER BY id
            """
            if args.limit:
                sql += " LIMIT %s"
                cur.execute(sql, (args.limit,))
            else:
                cur.execute(sql)
            delete_ids = []
            update_rows = []
            scanned = 0
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for r in rows:
                    scanned += 1
                    name = str(r.get("product_name_normalized") or r.get("product_name_raw") or "")
                    category = str(r.get("category_code") or "").strip()
                    resolved = _resolve_embedded_category(name, category)
                    is_goods = classify_fact_kind(
                        entity_type=r.get("entity_type"), name=name
                    ) == "GOODS"
                    if not is_goods or category in ("", "unknown") or resolved is None:
                        delete_ids.append(int(r["id"]))
                    elif resolved != category:
                        update_rows.append((resolved, int(r["id"])))
        print(f"SCANNED={scanned}")
        print(f"DELETE={len(delete_ids)} UPDATE_CATEGORY={len(update_rows)}")
        if not args.apply:
            print("DRY_RUN=YES (no writes)")
            return 0

        with conn.cursor() as cur:
            for i in range(0, len(update_rows), 1000):
                batch = update_rows[i:i+1000]
                psycopg2.extras.execute_values(
                    cur,
                    "UPDATE structured_entities SET category_code=data.v FROM (VALUES %s) AS data(v,id) WHERE structured_entities.id=data.id",
                    batch,
                    template="(%s,%s)",
                    page_size=1000,
                )
            for i in range(0, len(delete_ids), 1000):
                batch = delete_ids[i:i+1000]
                cur.execute(
                    "DELETE FROM structured_entities WHERE id = ANY(%s)",
                    (batch,),
                )
        conn.commit()
        print(f"APPLIED DELETE={len(delete_ids)} UPDATE={len(update_rows)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
