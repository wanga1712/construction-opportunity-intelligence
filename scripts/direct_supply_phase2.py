#!/usr/bin/env python3
"""DIRECT_SUPPLY Phase 2 inventory/download/fact dry-run."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

CRM_ROOT = "/opt/CRM_Streamlit"
for path in (CRM_ROOT, "/opt/tender_documents_research"):
    if path not in sys.path:
        sys.path.insert(0, path)

from document_processor.direct_template_registry import (  # noqa: E402
    normalize_direct_track,
    normalize_file_format,
    resolve_direct_template,
)

ENV_FILES = (
    "/opt/CRM_Streamlit/.env",
    "/opt/tender_documents_research/.env",
    "/etc/tender-docs-db.env",
    "/etc/tender-docs-worker-open.env",
    "/etc/tender-docs-s13v2-overlay.env",
    "/etc/tender-docs-s13-local-db.env",
)


def _load_env() -> None:
    for path in ENV_FILES:
        try:
            load_dotenv(path, override=False)
        except PermissionError:
            pass


def _connections():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    crm = psycopg2.connect(**dict(require_crm_db_connect_kwargs()))
    di = psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )
    return crm, di


def inventory() -> list[dict]:
    _load_env()
    crm, di = _connections()
    try:
        with crm.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT procurement_id, commercial_category_code
                  FROM crm_procurement_category_opportunities
                 WHERE status='CURRENT'
                   AND opportunity_track='DIRECT_SUPPLY'
            """)
            current = {(int(pid), str(cat)) for pid, cat in cur.fetchall()}
        with di.cursor() as cur:
            cur.execute("""
                SELECT q.id,q.procurement_id,q.category_codes,q.selected_documents,
                       f.id AS document_file_id,f.source_table,f.source_id,
                       q.contract_number,f.url,f.file_name AS db_file_name,
                       f.local_path,f.download_status,f.local_deleted_at
                  FROM document_processing_queue q
                  CROSS JOIN LATERAL jsonb_array_elements(q.selected_documents) e
                  LEFT JOIN document_files f
                    ON f.id=NULLIF(e->>'source_document_id','')::bigint
                 WHERE q.selected_documents IS NOT NULL
                   AND jsonb_typeof(q.selected_documents)='array'
                   AND jsonb_array_length(q.selected_documents)>0
            """)
            rows = cur.fetchall()
    finally:
        crm.close()
        di.close()

    out, seen = [], set()
    for qid, pid, cats, docs, file_id, table, sid, contract, url, db_name, local, status, deleted in rows:
        for entry in docs or []:
            if normalize_direct_track(entry.get("track")) != "DIRECT_SUPPLY":
                continue
            category = str(entry.get("category") or "").strip().lower()
            if not category and cats:
                category = str(cats[0]).lower()
            if (int(pid), category) not in current:
                continue
            fmt = normalize_file_format(Path(str(entry.get("file_name") or "")).suffix)
            doc_class = str(entry.get("document_class") or "OTHER").upper()
            template = resolve_direct_template(
                category_code=category,
                opportunity_track="DIRECT_SUPPLY",
                document_class=doc_class,
                file_format=fmt,
            )
            if template is None:
                continue
            key = (int(pid), category, int(file_id or 0), doc_class, fmt)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "queue_id": int(qid),
                "procurement_id": int(pid),
                "category": category,
                "document_class": doc_class,
                "format": fmt,
                "file_name": entry.get("file_name") or db_name,
                "document_file_id": int(file_id) if file_id else None,
                "source_table": table,
                "source_id": int(sid) if sid else None,
                "contract_number": contract,
                "url": url,
                "local_path": local,
                "download_status": status,
                "local_deleted_at": deleted.isoformat() if deleted else None,
                "template": template.extractor,
            })
    return out


def download(items: list[dict], apply: bool) -> list[dict]:
    _load_env()
    by_file_id = {}
    for row in items:
        file_id = row.get("document_file_id")
        if file_id:
            by_file_id.setdefault(int(file_id), row)
    existing = [
        x for x in by_file_id.values()
        if x.get("local_path") and Path(x["local_path"]).exists()
    ]
    pending = [x for x in by_file_id.values() if x not in existing]
    print(f"INVENTORY={len(items)} EXISTING={len(existing)} PENDING={len(pending)}")
    if not apply:
        for row in pending:
            print(f"DRY_RUN document_file_id={row['document_file_id']} pid={row['procurement_id']}")
        return pending

    from document_processor.daemon import DocumentProcessorDaemon

    daemon = DocumentProcessorDaemon()
    downloader = daemon.downloader
    results = []
    for idx, row in enumerate(pending, 1):
        link = (
            row.get("url"), row.get("file_name"), row.get("document_file_id"),
            None,
        )
        item = dict(row)
        if not row.get("url"):
            item.update({"result": "NO_URL"})
        else:
            try:
                res = downloader.download_and_extract(
                    task_id=row["queue_id"],
                    links=[link],
                    procurement_id=row["procurement_id"],
                    source_id=row.get("source_id"),
                    table_source=row.get("source_table"),
                    contract_number=row.get("contract_number"),
                )
                item.update({
                    "result": "DOWNLOADED" if res.downloaded_count else "FAILED",
                    "attempted": res.attempted_count,
                    "downloaded": res.downloaded_count,
                    "failed": res.failed_count,
                    "files": [str(p) for p in res.files],
                })
            except Exception as exc:
                item.update({"result": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
        results.append(item)
        print(f"[{idx}/{len(pending)}] pid={row['procurement_id']} file={row['file_name']} result={item['result']}")
    return results


def fact_dryrun(items: list[dict]) -> dict:
    from document_processor.direct_runtime import direct_facts

    report = {
        "documents": len(items), "documents_present": 0, "documents_missing": 0,
        "documents_with_facts": 0, "documents_without_facts": 0,
        "facts": 0, "facts_missing_qty": 0, "facts_missing_unit": 0,
        "facts_bad_price_proof": 0, "by_category": Counter(),
        "failures": [],
    }
    for row in items:
        path = Path(str(row.get("local_path") or ""))
        if not path.is_file():
            report["documents_missing"] += 1
            report["failures"].append({**row, "result": "FILE_MISSING"})
            continue
        report["documents_present"] += 1
        try:
            facts = direct_facts(
                path,
                procurement_id=row["procurement_id"],
                category_code=row["category"],
                document_name=row["file_name"],
                source_document_id=row["document_file_id"],
                physical_key=None,
                document_class=row["document_class"],
            )
        except Exception as exc:
            report["failures"].append({**row, "result": f"ERROR:{type(exc).__name__}:{exc}"})
            continue
        if facts:
            report["documents_with_facts"] += 1
        else:
            report["documents_without_facts"] += 1
        report["facts"] += len(facts)
        report["by_category"][row["category"]] += len(facts)
        for fact in facts:
            report["facts_missing_qty"] += int(fact.quantity_value is None)
            report["facts_missing_unit"] += int(not fact.unit_normalized)
            report["facts_bad_price_proof"] += int(
                (fact.unit_price_value is not None or fact.line_total_value is not None)
                and fact.layout_status != "CONSISTENT"
            )
    report["by_category"] = dict(report["by_category"])
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=("inventory", "download", "dryrun"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    items = inventory()
    if args.mode == "inventory":
        payload = {"count": len(items), "items": items}
    elif args.mode == "download":
        payload = {"download_results": download(items, args.apply)}
    else:
        payload = fact_dryrun(items)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
