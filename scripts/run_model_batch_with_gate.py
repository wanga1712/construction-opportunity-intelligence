#!/usr/bin/env python3
"""Run the daily model batch only after a parsed source+GOODS pool exists."""
from __future__ import annotations

import os
import sys

import psycopg2
from dotenv import load_dotenv

CRM_ROOT = "/opt/CRM_Streamlit"
if CRM_ROOT not in sys.path:
    sys.path.insert(0, CRM_ROOT)

MIN_CANDIDATES = int(os.getenv("MODEL_MIN_PARSED_CANDIDATES", "50"))
MODEL_BATCH_SIZE = int(os.getenv("MODEL_BATCH_SIZE", "50"))
RUNTIME_CAP_SEC = int(os.getenv("MODEL_RUNTIME_CAP_SEC", "10800"))


def _connection_kwargs() -> tuple[dict, dict]:
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    crm_kwargs = dict(require_crm_db_connect_kwargs())
    di_kwargs = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }
    return crm_kwargs, di_kwargs


def scoped_candidate_count() -> int:
    from src.services.match_source_filter import (
        NON_RESEARCHABLE_PATTERNS,
        RESEARCHABLE_PATTERNS,
    )
    from src.services.works_vs_goods_service import (
        NUMBER_PREFIX_REGEX_PATTERN,
        WORK_NAME_REGEX_PATTERN,
    )

    crm_kwargs, di_kwargs = _connection_kwargs()
    with psycopg2.connect(**crm_kwargs) as crm, psycopg2.connect(**di_kwargs) as di:
        with crm.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT procurement_id, commercial_category_code
                  FROM crm_procurement_category_opportunities
                 WHERE status='CURRENT'
                   AND commercial_state IN ('ACTIVE','FOLLOW_UP_AWARDED')
            """)
            current_pairs = {(int(pid), str(cat)) for pid, cat in cur.fetchall()}
        if not current_pairs:
            return 0

        researchable = [f"%{value}%" for value in RESEARCHABLE_PATTERNS]
        non_researchable = [f"%{value}%" for value in NON_RESEARCHABLE_PATTERNS]
        with di.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT se.procurement_id, se.category_code
                  FROM structured_entities se
                  JOIN document_files f ON f.id=se.source_document_id
                 WHERE lower(coalesce(f.file_name,'')) LIKE ANY(%s::text[])
                   AND lower(coalesce(f.file_name,'')) NOT LIKE ALL(%s::text[])
                   AND upper(coalesce(se.entity_type,'')) <> 'WORK'
                   AND regexp_replace(
                         coalesce(se.product_name_raw,''), %s, ''
                       ) !~* %s
            """, (
                researchable,
                non_researchable,
                NUMBER_PREFIX_REGEX_PATTERN,
                WORK_NAME_REGEX_PATTERN,
            ))
            parsed_pairs = {(int(pid), str(cat)) for pid, cat in cur.fetchall()}
        return len(current_pairs & parsed_pairs)


def main() -> int:
    for path in (
        "/opt/CRM_Streamlit/.env",
        "/opt/tender_documents_research/.env",
        "/etc/tender-docs-db.env",
    ):
        try:
            load_dotenv(path, override=False)
        except PermissionError:
            # systemd loads protected EnvironmentFile entries before this script.
            pass

    count = scoped_candidate_count()
    print(
        f"MODEL_BATCH_GATE parsed_candidates={count} "
        f"minimum={MIN_CANDIDATES} batch={MODEL_BATCH_SIZE}",
        flush=True,
    )
    if count < MIN_CANDIDATES:
        print("MODEL_BATCH_SKIPPED=backpressure_insufficient_parsed_candidates", flush=True)
        return 0
    if "--check-only" in sys.argv[1:]:
        print("MODEL_BATCH_GATE=PASS", flush=True)
        return 0

    runner = "/opt/CRM_Streamlit/src/services/crm_ai_assessment_runner.py"
    os.execv(sys.executable, [
        sys.executable,
        runner,
        "--drain",
        "--limit", str(MODEL_BATCH_SIZE),
        "--max-runtime-sec", str(RUNTIME_CAP_SEC),
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
