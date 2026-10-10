"""Parse-time extraction: estimates (tables) and project metadata (R4-PD).

Retention deletes raw files after 3 days, so everything we may ever need must be
extracted while the file is still on disk. This hook runs right after a document
is parsed and persists:
  * estimate material rows  -> structured_entities (MANUAL_PROOF_QUARANTINE)
  * project organizations / people -> project_metadata_* (raw + source_quote)
Fail-safe by design: any error is logged and never breaks parsing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("parse_extractors")

_DDL = (
    """CREATE TABLE IF NOT EXISTS project_metadata_organizations (
         id bigserial PRIMARY KEY,
         procurement_id bigint NOT NULL,
         organization_name_raw text NOT NULL,
         organization_role_raw text,
         document_name text,
         page_or_sheet text,
         source_quote text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT NOW()
       )""",
    """CREATE TABLE IF NOT EXISTS project_metadata_people (
         id bigserial PRIMARY KEY,
         procurement_id bigint NOT NULL,
         person_name_raw text NOT NULL,
         role_raw text,
         organization_name_raw text,
         document_name text,
         page_or_sheet text,
         source_quote text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT NOW()
       )""",
)


def _connect():
    from dotenv import load_dotenv

    load_dotenv("/opt/CRM_Streamlit/.env", override=True)
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
    )
    return conn


def _persist_estimate(conn, path: Path, procurement_id: int, document_name: str) -> int:
    from document_processor.smeta_forma_4b import detect_forma_4b, read_estimate, xlsx_sheet_names
    from document_processor.xlsx_table_reader import read_tables

    if detect_forma_4b(xlsx_sheet_names(path)):
        facts = read_estimate(path)
    else:
        facts = read_tables(path)
    if not facts:
        return 0
    cur = conn.cursor()
    cur.execute(
        "SELECT MIN(id) FROM document_match_details WHERE procurement_id=%s",
        (procurement_id,),
    )
    detail_id = cur.fetchone()[0] or 0
    payload = json.dumps([getattr(f, "__dict__", {}) for f in facts], ensure_ascii=False, default=str)
    cur.execute(
        """INSERT INTO structured_extraction_runs
             (detail_id, procurement_id, category_code, document_name, page_or_sheet,
              source_text_snapshot, source_text_sha256, source_validator_name,
              source_validator_version, source_validation_method, extractor_name,
              extractor_version, extraction_method, prompt_version, model_name, status,
              created_at, completed_at, structured_fact_trust_state)
           VALUES (%s,%s,%s,%s,'sheet1',%s,%s,'PROVENANCE_CONTRACT','v1','PARSE_TIME',
                   'PARSE_TIME_READER','v1','DETERMINISTIC_TABLE_MAP','none','none','COMPLETED',
                   NOW(),NOW(),'MANUAL_PROOF_QUARANTINE')
           ON CONFLICT (detail_id, extractor_version) DO UPDATE
             SET source_text_snapshot = EXCLUDED.source_text_snapshot,
                 source_text_sha256 = EXCLUDED.source_text_sha256,
                 completed_at = NOW()
           RETURNING id""",
        (detail_id, procurement_id,
         getattr(facts[0], "category_code", "unknown"), document_name,
         payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()),
    )
    run_id = cur.fetchone()[0]
    saved = 0
    for fact in facts:
        name = getattr(fact, "product_name_raw", None)
        if not name:
            continue
        fingerprint = hashlib.sha256(
            f"{procurement_id}|{name}|{getattr(fact, 'row', '')}".encode("utf-8")
        ).hexdigest()
        cur.execute(
            """INSERT INTO structured_entities
                 (run_id, detail_id, procurement_id, category_code, entity_fingerprint,
                  entity_type, product_name_raw, product_name_normalized, quantity_value,
                  quantity_raw, quantity_unit_raw, quantity_unit_normalized,
                  unit_price_value, unit_price_raw, total_price_value, total_price_raw,
                  currency_code, source_quote, confidence, product_relation, created_at,
                  structured_fact_trust_state)
               VALUES (%s,%s,%s,%s,%s,'PRODUCT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUB',%s,0.9,
                       'EMBEDDED',NOW(),'MANUAL_PROOF_QUARANTINE')""",
            (run_id, detail_id, procurement_id, getattr(fact, "category_code", "unknown"),
             fingerprint, name, name, getattr(fact, "quantity_value", None),
             str(getattr(fact, "quantity_value", "")), getattr(fact, "quantity_unit", ""),
             getattr(fact, "quantity_unit", ""), getattr(fact, "unit_price_value", None),
             str(getattr(fact, "unit_price_value", "")), getattr(fact, "total_price_value", None),
             str(getattr(fact, "total_price_value", "")), getattr(fact, "source_quote", "")),
        )
        saved += 1
    return saved


def _persist_metadata(conn, text: str, procurement_id: int, document_name: str) -> int:
    from document_processor.project_metadata_reader import scan_lines

    hits = scan_lines((text or "").splitlines())
    if not hits:
        return 0
    cur = conn.cursor()
    saved = 0
    for hit in hits:
        if hit.kind == "PERSON":
            cur.execute(
                """INSERT INTO project_metadata_people
                     (procurement_id, person_name_raw, role_raw, document_name, source_quote)
                   VALUES (%s,%s,%s,%s,%s)""",
                (procurement_id, hit.raw_value, hit.role_bucket, document_name, hit.source_quote),
            )
        else:
            cur.execute(
                """INSERT INTO project_metadata_organizations
                     (procurement_id, organization_name_raw, organization_role_raw,
                      document_name, source_quote)
                   VALUES (%s,%s,%s,%s,%s)""",
                (procurement_id, hit.raw_value, hit.role_bucket, document_name, hit.source_quote),
            )
        saved += 1
    return saved


def extract_and_persist(
    path: Any,
    text: Optional[str],
    procurement_id: Optional[int],
    document_name: Optional[str] = None,
) -> Dict[str, int]:
    """Best-effort parse-time extraction; never raises."""
    result = {"facts": 0, "metadata": 0}
    if procurement_id is None:
        return result
    try:
        path = Path(path)
        name = document_name or path.name
        conn = _connect()
        try:
            conn.cursor().execute("SELECT 1")
            for statement in _DDL:
                conn.cursor().execute(statement)
            conn.commit()
            if path.suffix.lower() in (".xlsx", ".xlsm"):
                result["facts"] = _persist_estimate(conn, path, int(procurement_id), name)
            if text:
                result["metadata"] = _persist_metadata(conn, text, int(procurement_id), name)
            conn.commit()
        finally:
            conn.close()
        if result["facts"] or result["metadata"]:
            logger.info(
                "parse-time extraction: facts=%d metadata=%d doc=%s",
                result["facts"], result["metadata"], name,
            )
    except Exception as exc:
        logger.warning("parse-time extraction failed for %s: %s", document_name, exc)
    return result
