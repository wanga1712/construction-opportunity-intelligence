#!/usr/bin/env python3
"""DIRECT_SUPPLY Phase 3: persist strict facts for downloaded DIRECT docs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2

CRM_ROOT = "/opt/CRM_Streamlit"
for path in (CRM_ROOT, "/opt/tender_documents_research", "/opt/CRM_Streamlit/scripts"):
    if path not in sys.path:
        sys.path.insert(0, path)

from direct_supply_phase2 import inventory  # noqa: E402
from document_processor.direct_runtime import direct_facts  # noqa: E402
from document_processor.embedded_persistence import persist_facts  # noqa: E402


def _di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def _count_for(procurement_id: int) -> int:
    conn = _di_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM structured_entities WHERE procurement_id=%s",
                (procurement_id,),
            )
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def _global_counts() -> tuple[int, int, int]:
    conn = _di_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  count(*),
                  count(*) FILTER (WHERE entity_type <> 'WORK' AND quantity_value IS NULL),
                  count(*) FILTER (WHERE entity_type <> 'WORK' AND coalesce(quantity_unit_normalized,'') = '')
                FROM structured_entities
                """
            )
            total, missing_qty, missing_unit = cur.fetchone()
            return int(total or 0), int(missing_qty or 0), int(missing_unit or 0)
    finally:
        conn.close()


def _persist_item(row: dict) -> tuple[int, int]:
    path = Path(str(row.get("local_path") or ""))
    if not path.is_file():
        return 0, 0
    facts = direct_facts(
        path,
        procurement_id=row["procurement_id"],
        category_code=row["category"],
        document_name=row["file_name"],
        source_document_id=row.get("document_file_id"),
        physical_key=row.get("physical_key"),
        document_class=row.get("document_class"),
    )
    facts = [
        f for f in facts
        if f.quantity_value is not None and f.unit_normalized
    ]
    if not facts:
        return 0, 0
    snapshot = "\n".join(str(getattr(f, "source_quote", "") or "") for f in facts)
    conn = _di_conn()
    try:
        created, reused, _stats = persist_facts(
            conn,
            procurement_id=row["procurement_id"],
            document_name=row["file_name"],
            category_code=row["category"],
            facts=facts,
            source_text=snapshot,
            source_document_id=row.get("document_file_id"),
        )
        conn.commit()
        return int(created or 0), int(reused or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary-procurement-id", type=int)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if not (args.canary_procurement_id or args.all):
        ap.error("use --canary-procurement-id or --all")

    items = inventory()
    if args.canary_procurement_id:
        items = [
            r for r in items
            if r["procurement_id"] == args.canary_procurement_id
        ]

    before_global = _global_counts()
    before_proc = (
        _count_for(args.canary_procurement_id)
        if args.canary_procurement_id else None
    )
    report = {"items": len(items), "created": 0, "reused": 0, "processed": []}
    for row in items:
        try:
            created, reused = _persist_item(row)
        except Exception as exc:
            report["processed"].append({
                **row,
                "result": f"ERROR:{type(exc).__name__}:{exc}",
            })
            continue
        report["created"] += created
        report["reused"] += reused
        report["processed"].append({
            "procurement_id": row["procurement_id"],
            "document_file_id": row.get("document_file_id"),
            "category": row["category"],
            "file_name": row["file_name"],
            "created": created,
            "reused": reused,
        })

    after_global = _global_counts()
    after_proc = (
        _count_for(args.canary_procurement_id)
        if args.canary_procurement_id else None
    )
    report["before_global"] = dict(zip(
        ("structured_facts", "missing_qty", "missing_unit"), before_global
    ))
    report["after_global"] = dict(zip(
        ("structured_facts", "missing_qty", "missing_unit"), after_global
    ))
    if before_proc is not None:
        report["before_procurement"] = before_proc
        report["after_procurement"] = after_proc
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
