#!/usr/bin/env python3
"""EMBEDDED_EXTRACTION_NORMALIZATION_V1 - Phase 4 canary (NO HTTP).

Re-parses the already-downloaded canary artifacts and runs the category-bound
extractor + normalizer over them, persisting structured facts with provenance.

Guarantees: NEW_HTTP_REQUESTS=0, workers/writers untouched.
"""

from __future__ import annotations

import json
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

DOC_RUNTIME = os.getenv("DOC_RUNTIME_PATH", "/opt/tender_documents_research")
if Path(DOC_RUNTIME).exists():
    RUNTIME = Path(DOC_RUNTIME)
else:
    RUNTIME = ROOT / "tender_documents_research"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from document_processor.embedded_extraction import (  # noqa: E402
    EXTRACTOR_VERSION,
    NORMALIZER_VERSION,
    extract_facts,
    facts_from_table_rows,
)
from document_processor.parser_factory import ParserFactory  # noqa: E402
from document_processor.parse_utils import (  # noqa: E402
    get_rich_parser,
    parse_file_with_meta,
    supports_rich_meta,
)

LANE = "queue_v2_canary"


def crm_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


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


def category_keywords(crm) -> Dict[str, List[str]]:
    """Category vocabulary from the canonical registry (document_search_plan)."""
    rows = query(
        crm,
        "SELECT category_code, document_search_plan FROM crm_product_categories WHERE is_active",
    )
    out: Dict[str, List[str]] = {}
    for r in rows:
        plan = r.get("document_search_plan") or []
        words: List[str] = []
        if isinstance(plan, list):
            for step in plan:
                target = ""
                if isinstance(step, dict):
                    target = str(step.get("target") or "")
                for part in target.split("|"):
                    part = part.strip().lower()
                    if len(part) >= 4 and part not in words:
                        words.append(part)
        out[r["category_code"]] = words
    return out


def _read_xlsx_facts(path: Path):
    from document_processor.smeta_forma_4b import detect_forma_4b, read_estimate, xlsx_sheet_names
    from document_processor.xlsx_table_reader import read_tables

    try:
        if detect_forma_4b(xlsx_sheet_names(path)):
            return read_estimate(path)
    except Exception:
        pass
    try:
        return read_tables(path)
    except Exception:
        return []


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        vocab = category_keywords(crm)
        lane = query(
            di,
            "SELECT id, procurement_id, category_codes, selected_source_document_ids,"
            " soft_fallback_source_document_ids, selected_documents"
            " FROM document_processing_queue WHERE queue_lane=%s ORDER BY id",
            (LANE,),
        )
        pids = sorted({int(r["procurement_id"]) for r in lane})

        docs = query(
            di,
            "SELECT id, procurement_id, file_name, physical_download_key, url_hash, url,"
            " local_path, download_status,"
            " (local_path IS NOT NULL AND local_deleted_at IS NULL) AS has_local_file"
            " FROM document_files WHERE procurement_id = ANY(%s)",
            (pids,),
        )

        # Idempotent re-run: drop previous canary extraction for these pids.
        with di.cursor() as cur:
            cur.execute(
                "DELETE FROM structured_extraction_runs"
                " WHERE procurement_id = ANY(%s) AND extractor_version = %s",
                (pids, EXTRACTOR_VERSION),
            )
        di.commit()

        # source_document_id -> category chosen by the plan
        doc_category: Dict[int, str] = {}
        for row in lane:
            for entry in row.get("selected_documents") or []:
                sid = entry.get("source_document_id")
                if sid is not None and entry.get("category"):
                    doc_category[int(sid)] = entry["category"]
            cats = row.get("category_codes") or []
            for sid in (row.get("selected_source_document_ids") or []):
                doc_category.setdefault(int(sid), cats[0] if cats else "unknown")

        factory = ParserFactory()
        counters = Counter()
        per_category = defaultdict(Counter)
        seen_paths = set()
        selected_ids = {int(i) for r in lane for i in (r.get("selected_source_document_ids") or [])}

        for doc in docs:
            doc_id = int(doc["id"])
            if doc_id not in selected_ids:
                continue
            local_path = doc.get("local_path")
            if not local_path:
                continue
            path = Path(local_path)
            if not path.exists() or not path.is_file():
                counters["LOCAL_ARTIFACT_MISSING"] += 1
                continue
            if str(path) in seen_paths:
                continue
            seen_paths.add(str(path))
            pid = int(doc["procurement_id"])
            category = doc_category.get(doc_id, "unknown")
            counters["EMBEDDED_DOCS_REPROCESSED"] += 1
            if category == "unknown":
                counters["CATEGORY_CODE_UNKNOWN"] += 1

            facts = []
            if path.suffix.lower() in {".xlsx", ".xlsm"}:
                rows = _read_xlsx_facts(path)
                facts = facts_from_table_rows(
                    procurement_id=pid, category_code=category, document_name=doc["file_name"],
                    rows=rows, source_document_id=doc_id,
                    physical_key=doc.get("physical_download_key"),
                    category_keywords=vocab.get(category, []),
                )
            else:
                parser = (
                    get_rich_parser(factory, path)
                    if supports_rich_meta(path)
                    else factory.get_parser(path)
                )
                if parser is None:
                    counters["UNSUPPORTED_FORMAT"] += 1
                    continue
                text, line_meta = parse_file_with_meta(parser, path)
                counters["CATEGORY_EXTRACTOR_CALLED"] += 1
                facts = extract_facts(
                    procurement_id=pid, category_code=category, document_name=doc["file_name"],
                    text=text, line_meta=line_meta, source_document_id=doc_id,
                    physical_key=doc.get("physical_download_key"),
                    category_keywords=vocab.get(category, []),
                )

            if facts:
                counters["NORMALIZER_CALLED"] += 1
                _persist(di, doc, category, facts, counters)
                for f in facts:
                    per_category[category]["FACTS"] += 1
                    if f.product_name_raw:
                        per_category[category]["MATERIAL"] += 1
                    if f.quantity_value is not None:
                        per_category[category]["QUANTITY"] += 1
                    if f.unit_normalized:
                        per_category[category]["UNIT"] += 1
                    if f.unit_price_value is not None:
                        per_category[category]["UNIT_PRICE"] += 1
                    if f.line_total_value is not None:
                        per_category[category]["TOTAL"] += 1
        di.commit()

        print("=" * 78)
        print("PHASE 4 - EMBEDDED EXTRACTION CANARY (artifact-only, HTTP=0)")
        for key in (
            "EMBEDDED_DOCS_REPROCESSED",
            "CATEGORY_EXTRACTOR_CALLED",
            "NORMALIZER_CALLED",
            "UNSUPPORTED_FORMAT",
            "LOCAL_ARTIFACT_MISSING",
            "CATEGORY_CODE_UNKNOWN",
            "MATERIAL_FOUND",
            "QUANTITY_FOUND",
            "UNIT_FOUND",
            "UNIT_PRICE_FOUND",
            "CATEGORY_VALUE_FOUND",
            "STRUCTURED_ENTITIES_WRITTEN",
            "STRUCTURED_ENTITIES_WITH_CATEGORY",
            "STRUCTURED_ENTITIES_WITH_PROVENANCE",
            "DUPLICATE_ENTITY_VALUE_SUM",
        ):
            print(f"{key}={counters.get(key, 0)}")
        print(f"PER_CATEGORY={ {k: dict(v) for k, v in sorted(per_category.items())} }")
        return 0
    finally:
        crm.close()
        di.close()


def _persist(di, doc: Dict[str, Any], category: str, facts, counters: Counter) -> None:
    pid = int(doc["procurement_id"])
    doc_name = doc["file_name"]
    cur = di.cursor()
    cur.execute(
        "SELECT MIN(id) FROM document_match_details WHERE procurement_id=%s", (pid,)
    )
    detail_id = cur.fetchone()[0]
    snapshot = json.dumps([f.source_quote for f in facts][:200], ensure_ascii=False)
    import hashlib as _h

    cur.execute(
        """
        INSERT INTO structured_extraction_runs
            (detail_id, procurement_id, category_code, document_name, page_or_sheet,
             source_text_snapshot, source_text_sha256, source_validator_name,
             source_validator_version, source_validation_method, extractor_name,
             extractor_version, extraction_method, prompt_version, model_name, status,
             created_at, completed_at, structured_fact_trust_state)
        VALUES (%s,%s,%s,%s,'mixed',%s,%s,'PROVENANCE_CONTRACT','v1','PARSE_TIME',
                'EMBEDDED_EXTRACTOR',%s,'DETERMINISTIC_ROW_MAP','none','none','COMPLETED',
                NOW(),NOW(),'MANUAL_PROOF_QUARANTINE')
        ON CONFLICT (detail_id, extractor_version) DO UPDATE
          SET source_text_snapshot = EXCLUDED.source_text_snapshot,
              source_text_sha256 = EXCLUDED.source_text_sha256,
              category_code = EXCLUDED.category_code,
              completed_at = NOW()
        RETURNING id
        """,
        (detail_id, pid, category, doc_name, snapshot,
         _h.sha256(snapshot.encode("utf-8")).hexdigest(), EXTRACTOR_VERSION),
    )
    run_id = cur.fetchone()[0]
    for f in facts:
        unit_raw = (f.unit_raw or None) and str(f.unit_raw)[:100]
        unit_norm = (f.unit_normalized or None) and str(f.unit_normalized)[:100]
        category_val = str(f.category_code or "unknown")[:100]
        cur.execute(
            """
            INSERT INTO structured_entities
                (run_id, detail_id, procurement_id, category_code, entity_fingerprint,
                 entity_type, product_name_raw, product_name_normalized,
                 quantity_value, quantity_raw, quantity_unit_raw, quantity_unit_normalized,
                 measurement_family, unit_price_value, unit_price_raw,
                 total_price_value, total_price_raw, currency_code, source_quote,
                 confidence, product_relation, created_at, structured_fact_trust_state,
                 source_document_id, physical_download_key, page_or_sheet, row_or_line,
                 extractor_version, normalizer_version)
            VALUES (%s,%s,%s,%s,%s,'PRODUCT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUB',%s,
                    %s,'EMBEDDED',NOW(),'MANUAL_PROOF_QUARANTINE',%s,%s,%s,%s,%s,%s)
            ON CONFLICT (run_id, entity_fingerprint) DO NOTHING
            """,
            (
                run_id, detail_id, pid, category_val, f.entity_fingerprint,
                (f.product_name_raw or "")[:400], f.product_name_normalized,
                f.quantity_value, f.quantity_raw, unit_raw, unit_norm,
                f.measurement_family, f.unit_price_value, f.unit_price_raw,
                f.line_total_value, f.line_total_raw, f.source_quote, f.confidence,
                f.source_document_id, f.physical_download_key, f.page_or_sheet,
                f.row_or_line, f.extractor_version, f.normalizer_version,
            ),
        )
        if cur.rowcount == 0:
            counters["DUPLICATE_ENTITY_VALUE_SUM"] += 1
        else:
            counters["STRUCTURED_ENTITIES_WRITTEN"] += 1
            if f.category_code and f.category_code != "unknown":
                counters["STRUCTURED_ENTITIES_WITH_CATEGORY"] += 1
            if f.source_document_id and f.source_quote:
                counters["STRUCTURED_ENTITIES_WITH_PROVENANCE"] += 1
            if f.product_name_raw:
                counters["MATERIAL_FOUND"] += 1
            if f.quantity_value is not None:
                counters["QUANTITY_FOUND"] += 1
            if f.unit_normalized:
                counters["UNIT_FOUND"] += 1
            if f.unit_price_value is not None:
                counters["UNIT_PRICE_FOUND"] += 1
            if f.line_total_value is not None:
                counters["CATEGORY_VALUE_FOUND"] += 1


if __name__ == "__main__":
    raise SystemExit(main())
