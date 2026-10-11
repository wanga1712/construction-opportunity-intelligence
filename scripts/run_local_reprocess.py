#!/usr/bin/env python3
"""EMBEDDED_EXTRACTION_NORMALIZATION_V1 - Step 1: reprocess LOCAL PRESENT only.

Re-runs DOCUMENT_SELECTION_V3 over the whole CURRENT base, keeps only selected
documents whose local artifact is physically present, and pushes them through
EMBEDDED_EXTRACTOR_V1 / UNIT_NORMALIZER_V1.

Guarantees: NEW_HTTP_REQUESTS=0, workers/writers off, no CRM/queue/medal writes.
Writes only extraction results, idempotently (re-run reuses entities).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

DOC_RUNTIME = os.getenv("DOC_RUNTIME_PATH", "/opt/tender_documents_research")
RUNTIME = Path(DOC_RUNTIME) if Path(DOC_RUNTIME).exists() else ROOT / "tender_documents_research"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from src.services.commercial_routing_v3.queue_plan_v2 import build_queue_plan_v2  # noqa: E402
from src.services.commercial_routing_v3.research_action_v2 import (  # noqa: E402
    GROUP_DIRECT,
    GROUP_EMBEDDED,
    decide_research_action,
    track_group,
)
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

PIPELINE_GENERATION = os.getenv("DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT")

_MAGIC = {
    ".pdf": (b"%PDF",),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".xlsx": (b"PK\x03\x04",),
    ".xlsm": (b"PK\x03\x04",),
    ".odt": (b"PK\x03\x04",),
    ".zip": (b"PK\x03\x04",),
}


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


OPP_SQL = """
SELECT o.procurement_id, o.commercial_category_code AS category_code,
       o.status AS opportunity_status, o.opportunity_track, o.commercial_state,
       o.commercial_priority_score, o.candidate_initial_medal, o.current_effective_medal,
       p.id AS id, p.crm_stage, p.award_status, p.source_status,
       p.start_date, p.end_date, p.delivery_start_date, p.delivery_end_date,
       p.execution_start_at, p.execution_end_at
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
 WHERE o.status = 'CURRENT'
"""

DOCS_SQL = """
SELECT id, procurement_id, source_table, source_id, url, url_hash, file_name,
       physical_download_key, download_status, local_path, local_deleted_at
  FROM document_files WHERE procurement_id = ANY(%s)
"""


def local_present(doc: Dict[str, Any], cache: Dict[str, bool]) -> bool:
    if doc.get("local_deleted_at") is not None or not doc.get("local_path"):
        return False
    key = str(doc["local_path"])
    if key in cache:
        return cache[key]
    p = Path(key)
    ok = p.exists() and p.is_file()
    if ok:
        expected = _MAGIC.get(p.suffix.lower())
        if expected:
            try:
                with p.open("rb") as fh:
                    head = fh.read(8)
                ok = any(head.startswith(sig) for sig in expected)
            except Exception:
                ok = False
    cache[key] = ok
    return ok


def category_keywords(crm) -> Dict[str, List[str]]:
    rows = query(crm, "SELECT category_code, document_search_plan FROM crm_product_categories WHERE is_active")
    out: Dict[str, List[str]] = {}
    for r in rows:
        words: List[str] = []
        plan = r.get("document_search_plan") or []
        if isinstance(plan, list):
            for step in plan:
                target = str(step.get("target") or "") if isinstance(step, dict) else ""
                for part in target.split("|"):
                    part = part.strip().lower()
                    if len(part) >= 4 and part not in words:
                        words.append(part)
        out[r["category_code"]] = words
    return out


def read_xlsx_facts(path: Path):
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
        opps = query(crm, OPP_SQL)
        by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in opps:
            by_pid[int(row["procurement_id"])].append(row)

        assets = {
            int(r["procurement_id"]): dict(r)
            for r in query(
                di,
                "SELECT procurement_id, count(*) FILTER (WHERE download_status='COMPLETED'"
                " AND local_path IS NOT NULL AND local_deleted_at IS NULL) AS local_present"
                " FROM document_files GROUP BY 1",
            )
        }
        evidence = {
            (int(r["procurement_id"]), r["category_code"])
            for r in query(
                di,
                "SELECT DISTINCT m.procurement_id, d.category_code"
                " FROM document_match_details d JOIN document_matches m ON m.id=d.match_id",
            )
        }
        pids_with_docs = {
            int(r["procurement_id"])
            for r in query(di, "SELECT DISTINCT procurement_id FROM document_files")
        }
        for pid, items in by_pid.items():
            apid = assets.get(pid, {})
            for item in items:
                decision = decide_research_action(
                    category_code=item["category_code"],
                    opportunity_track=item["opportunity_track"],
                    commercial_state=item["commercial_state"],
                    candidate_medal=item["candidate_initial_medal"],
                    has_confirmed_facts=(pid, item["category_code"]) in evidence,
                    has_reusable_artifacts=bool(apid.get("local_present")),
                    window_closed=str(item["commercial_state"] or "").upper()
                    in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"},
                )
                item["research_action_v2"] = decision.action.value

        plan_pids = [pid for pid in by_pid if pid in pids_with_docs]
        documents = query(di, DOCS_SQL, (plan_pids,)) if plan_pids else []
        docs_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for doc in documents:
            docs_by_pid[int(doc["procurement_id"])].append(doc)
        doc_by_id = {int(d["id"]): d for d in documents}

        cache: Dict[str, bool] = {}
        # (doc_id, pid, category, track_group, document_class)
        selected: List[Tuple[int, int, str, str, str]] = []
        for pid, items in by_pid.items():
            if pid not in docs_by_pid:
                continue
            plan = build_queue_plan_v2(
                procurement=items[0], opportunities=items,
                documents=docs_by_pid[pid], pipeline_generation=PIPELINE_GENERATION,
            )
            if not plan["selected_source_document_ids"]:
                continue
            cat_track = {i["category_code"]: track_group(i["opportunity_track"]) for i in items}
            for entry in plan["selected_documents"]:
                sid = entry.get("source_document_id")
                if sid is None:
                    continue
                doc = doc_by_id.get(int(sid))
                if doc is None or not local_present(doc, cache):
                    continue
                cat = entry.get("category") or (plan["category_codes"] or ["unknown"])[0]
                selected.append((int(sid), pid, cat, cat_track.get(cat, "UNKNOWN"),
                                 entry.get("document_class") or "OTHER"))

        counters = Counter()
        per_category = defaultdict(Counter)
        per_class = Counter()
        per_ext = Counter()
        counters["LOCAL_SELECTED_INPUT"] = len(selected)
        factory = ParserFactory()

        for doc_id, pid, category, track, doc_class in selected:
            doc = doc_by_id[doc_id]
            path = Path(doc["local_path"])
            ext = path.suffix.lower().lstrip(".")
            per_ext[ext] += 1
            per_class[doc_class] += 1
            if track == GROUP_DIRECT:
                counters["DIRECT_FILES"] += 1
            else:
                counters["EMBEDDED_FILES"] += 1

            facts = []
            parse_failed = False
            empty = False
            try:
                if path.suffix.lower() in {".xlsx", ".xlsm"}:
                    rows = read_xlsx_facts(path)
                    facts = facts_from_table_rows(
                        procurement_id=pid, category_code=category, document_name=doc["file_name"],
                        rows=rows, source_document_id=doc_id,
                        physical_key=doc.get("physical_download_key"),
                        category_keywords=vocab.get(category, []),
                    )
                    if not rows:
                        empty = True
                else:
                    parser = get_rich_parser(factory, path) if supports_rich_meta(path) else factory.get_parser(path)
                    if parser is None:
                        parse_failed = True
                    else:
                        text, line_meta = parse_file_with_meta(parser, path)
                        if not (text or "").strip():
                            empty = True
                        facts = extract_facts(
                            procurement_id=pid, category_code=category, document_name=doc["file_name"],
                            text=text, line_meta=line_meta, source_document_id=doc_id,
                            physical_key=doc.get("physical_download_key"),
                            category_keywords=vocab.get(category, []),
                        )
            except Exception:
                parse_failed = True

            if parse_failed:
                counters["FILES_FAILED"] += 1
                continue
            counters["FILES_PARSED"] += 1
            if empty:
                counters["FILES_EMPTY"] += 1
            if facts:
                counters["FILES_WITH_FACTS"] += 1
                created, reused = _persist(di, doc, category, facts, counters)
                for f in facts:
                    per_category[category]["FACTS"] += 1
                    per_category[category]["MATERIAL"] += 1 if f.product_name_raw else 0
                    per_category[category]["QUANTITY"] += 1 if f.quantity_value is not None else 0
                    per_category[category]["UNIT"] += 1 if f.unit_normalized else 0
                    per_category[category]["TOTAL"] += 1 if f.line_total_value is not None else 0
            else:
                counters["FILES_WITHOUT_FACTS"] += 1
        di.commit()

        print("=" * 78)
        print("STEP 1 - LOCAL REPROCESS (V3-selected, local-present, HTTP=0)")
        for key in (
            "LOCAL_SELECTED_INPUT", "FILES_PARSED", "FILES_FAILED", "FILES_EMPTY",
            "FILES_WITH_FACTS", "FILES_WITHOUT_FACTS", "EMBEDDED_FILES", "DIRECT_FILES",
            "ENTITIES_CREATED", "ENTITIES_REUSED", "DUPLICATE_ENTITIES_CREATED",
            "MATERIAL_FOUND", "QUANTITY_FOUND", "UNIT_FOUND", "UNIT_PRICE_FOUND",
            "CATEGORY_VALUE_FOUND", "WITH_CATEGORY", "WITH_PROVENANCE", "UNKNOWN_CATEGORY",
            "NEW_HTTP_REQUESTS",
        ):
            print(f"{key}={counters.get(key, 0)}")
        print(f"PER_CATEGORY={ {k: dict(v) for k, v in sorted(per_category.items())} }")
        print(f"PER_DOC_CLASS={dict(per_class)}")
        print(f"PER_EXT={dict(per_ext)}")
        return 0
    finally:
        crm.close()
        di.close()


def _persist(di, doc: Dict[str, Any], category: str, facts, counters: Counter):
    pid = int(doc["procurement_id"])
    doc_name = doc["file_name"]
    cur = di.cursor()
    cur.execute("SELECT MIN(id) FROM document_match_details WHERE procurement_id=%s", (pid,))
    detail_id = cur.fetchone()[0]
    snapshot = json.dumps([f.source_quote for f in facts][:200], ensure_ascii=False)
    # stable run identity: reuse the same run on repeat reprocess
    cur.execute(
        "SELECT id FROM structured_extraction_runs"
        " WHERE procurement_id=%s AND document_name=%s AND extractor_version=%s LIMIT 1",
        (pid, doc_name, EXTRACTOR_VERSION),
    )
    row = cur.fetchone()
    if row:
        run_id = row[0]
        cur.execute(
            "UPDATE structured_extraction_runs SET category_code=%s, source_text_snapshot=%s,"
            " source_text_sha256=%s, completed_at=NOW() WHERE id=%s",
            (category[:100], snapshot, hashlib.sha256(snapshot.encode("utf-8")).hexdigest(), run_id),
        )
    else:
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
            RETURNING id
            """,
            (detail_id, pid, category[:100], doc_name, snapshot,
             hashlib.sha256(snapshot.encode("utf-8")).hexdigest(), EXTRACTOR_VERSION),
        )
        run_id = cur.fetchone()[0]
    created = reused = 0
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
            ON CONFLICT (procurement_id, source_document_id, entity_fingerprint, extractor_version)
              WHERE extractor_version IS NOT NULL AND source_document_id IS NOT NULL
            DO NOTHING
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
            reused += 1
            counters["ENTITIES_REUSED"] += 1
        else:
            created += 1
            counters["ENTITIES_CREATED"] += 1
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
            if f.category_code and f.category_code != "unknown":
                counters["WITH_CATEGORY"] += 1
            else:
                counters["UNKNOWN_CATEGORY"] += 1
            if f.source_document_id and f.source_quote:
                counters["WITH_PROVENANCE"] += 1
    return created, reused


if __name__ == "__main__":
    raise SystemExit(main())
