#!/usr/bin/env python3
"""Read-only check of the Phase 4 model fallback for one section (SECTION_LEVEL_NORMALIZATION_V1).

Loads the section's material quotes from `structured_entities`, calls
`section_model_fallback.extract_sections_with_model` (qwen2.5:7b, hard JSON schema) and prints
the fail-closed validated result. No DB writes.

    cd /opt/CRM_Streamlit && set -a && . ./.env; set +a
    /opt/CRM_Streamlit/.venv313/bin/python scripts/audit_section_model_fallback.py \
        --procurement-id 148391 --section-code 'ПСК 1 стадия на торги::глава 1'
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2
import psycopg2.extras


def _conn():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kwargs.setdefault("connect_timeout", 8)
    return psycopg2.connect(**kwargs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procurement-id", type=int, default=148391)
    ap.add_argument("--section-code", required=True)
    ap.add_argument("--max-rows", type=int, default=30)
    args = ap.parse_args()

    sys.path.insert(0, "/opt/tender_documents_research")
    sys.path.insert(0, "/opt/CRM_Streamlit")
    from tender_documents_research.document_processor.section_model_fallback import (
        extract_sections_with_model,
        section_needs_fallback,
    )

    conn = _conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT product_name_normalized, product_name_raw, quantity_value,
                   quantity_unit_raw, total_price_value, source_quote, row_or_line,
                   section_total_price_value, section_total_source
              FROM structured_entities
             WHERE procurement_id = %s AND section_code = %s
             ORDER BY total_price_value DESC NULLS LAST, id
             LIMIT %s
            """,
            (args.procurement_id, args.section_code, args.max_rows),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("NO_ROWS for section", args.section_code)
        return 0
    total_value = rows[0].get("section_total_price_value")
    total_source = rows[0].get("section_total_source")
    need = section_needs_fallback(total_value, total_source)
    text = "\n".join(str(r.get("source_quote") or "") for r in rows if r.get("source_quote"))
    print("section:", args.section_code, "| rows:", len(rows),
          "| deterministic_total:", total_value, "| source:", total_source,
          "| fallback_needed:", need)
    print("input_chars:", len(text))

    result = extract_sections_with_model(text)
    if not result:
        print("MODEL_RESULT: NO_VALID_PAYLOAD (fail-closed)")
        return 0
    print("MODEL_RESULT: section_name=%r | total_raw=%r | total_value=%s | source=%s | trust=%s"
          % (result.get("section_name"), result.get("section_total_raw"),
             result.get("section_total_value"), result.get("section_total_source"),
             result.get("trust_state")))
    print("children:", len(result.get("children") or []))
    for child in (result.get("children") or [])[:5]:
        print("   -", child.get("material_name"), "|", child.get("quantity"), child.get("unit"),
              "|", child.get("total_value"), "|", str(child.get("source_quote"))[:70])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
