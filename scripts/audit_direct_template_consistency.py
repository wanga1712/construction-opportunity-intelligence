#!/usr/bin/env python3
"""Read-only DIRECT_SUPPLY template and strict-fact coverage audit."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

CRM_ROOT = "/opt/CRM_Streamlit"
if CRM_ROOT not in sys.path:
    sys.path.insert(0, CRM_ROOT)

from document_processor.direct_template_registry import (  # noqa: E402
    classify_direct_document,
    normalize_direct_track,
    normalize_file_format,
    resolve_direct_template,
)


def _env() -> tuple[dict, dict]:
    for path in (
        "/opt/CRM_Streamlit/.env",
        "/opt/tender_documents_research/.env",
        "/etc/tender-docs-db.env",
    ):
        try:
            load_dotenv(path, override=False)
        except PermissionError:
            pass
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    crm = dict(require_crm_db_connect_kwargs())
    di = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }
    return crm, di


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-out")
    args = ap.parse_args()
    crm_kwargs, di_kwargs = _env()
    result = {
        "current_direct_pairs": 0,
        "documents": Counter(),
        "classification": Counter(),
        "supported_documents": Counter(),
        "unsupported_documents": Counter(),
        "strict_facts": 0,
        "facts_missing_qty": 0,
        "facts_missing_unit": 0,
    }
    with psycopg2.connect(**crm_kwargs) as crm:
        with crm.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT procurement_id, commercial_category_code
                  FROM crm_procurement_category_opportunities
                 WHERE status='CURRENT'
                   AND opportunity_track='DIRECT_SUPPLY'
            """)
            current = {(int(pid), str(cat)) for pid, cat in cur.fetchall()}
    result["current_direct_pairs"] = len(current)

    with psycopg2.connect(**di_kwargs) as di:
        with di.cursor() as cur:
            cur.execute("""
                SELECT procurement_id, category_codes, selected_documents
                  FROM document_processing_queue
                 WHERE selected_documents IS NOT NULL
                   AND jsonb_typeof(selected_documents)='array'
                   AND jsonb_array_length(selected_documents)>0
            """)
            plans = cur.fetchall()
        for pid, category_codes, docs in plans:
            for entry in docs or []:
                if not isinstance(entry, dict):
                    continue
                if normalize_direct_track(entry.get("track")) != "DIRECT_SUPPLY":
                    continue
                category = str(entry.get("category") or "").strip().lower()
                if not category and category_codes:
                    category = str(category_codes[0]).lower()
                if (int(pid), category) not in current:
                    continue
                fmt = normalize_file_format(Path(str(entry.get("file_name") or "")).suffix)
                doc_class = str(entry.get("document_class") or "OTHER").upper()
                key = f"{category}|DIRECT_SUPPLY|{doc_class}|{fmt}"
                result["documents"][key] += 1
                template = resolve_direct_template(
                    category_code=category,
                    opportunity_track="DIRECT_SUPPLY",
                    document_class=doc_class,
                    file_format=fmt,
                )
                target = "supported_documents" if template else "unsupported_documents"
                result[target][key] += 1
                result["classification"][
                    classify_direct_document(
                        category_code=category,
                        opportunity_track="DIRECT_SUPPLY",
                        document_class=doc_class,
                        file_format=fmt,
                    )
                ] += 1

        with di.cursor() as cur:
            cur.execute("""
                SELECT procurement_id, category_code,
                       count(*) FILTER (WHERE entity_type <> 'WORK' AND quantity_value IS NOT NULL AND coalesce(quantity_unit_normalized,'') <> '') AS strict,
                       count(*) FILTER (WHERE entity_type <> 'WORK' AND quantity_value IS NULL) AS missing_qty,
                       count(*) FILTER (WHERE entity_type <> 'WORK' AND coalesce(quantity_unit_normalized,'') = '') AS missing_unit
                  FROM structured_entities
                 GROUP BY 1,2
            """)
            fact_rows = cur.fetchall()
    for pid, category, strict, missing_qty, missing_unit in fact_rows:
        if (int(pid), str(category)) not in current:
            continue
        result["strict_facts"] += int(strict or 0)
        result["facts_missing_qty"] += int(missing_qty or 0)
        result["facts_missing_unit"] += int(missing_unit or 0)
    result.update({
        "strict_facts": result["strict_facts"],
        "facts_missing_qty": result["facts_missing_qty"],
        "facts_missing_unit": result["facts_missing_unit"],
    })
    payload = {
        key: dict(value) if isinstance(value, Counter) else value
        for key, value in result.items()
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
