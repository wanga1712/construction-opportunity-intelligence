#!/usr/bin/env python3
"""TIER0 extraction from the worker's task directories (HTTP=0).

The targeted downloader stores artifacts under
`/data/tender-documents/downloads/<queue_id>/`. This runs the category-bound
EMBEDDED_EXTRACTOR_V1 over those artifacts, attributing each file to the plan's
source_document_id + category, and persists idempotently.
"""

from __future__ import annotations

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
RUNTIME = Path(DOC_RUNTIME) if Path(DOC_RUNTIME).exists() else ROOT / "tender_documents_research"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from document_processor.embedded_extraction import extract_facts, facts_from_table_rows  # noqa: E402
from document_processor.embedded_persistence import persist_facts  # noqa: E402
from document_processor.parser_factory import ParserFactory  # noqa: E402
from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta  # noqa: E402

LANE = "queue_v2_tier0"
DOWNLOAD_ROOT = Path(os.getenv("DOCUMENT_DOWNLOAD_DIR", "/data/tender-documents/downloads"))


def crm_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"), "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"), "password": os.getenv("CRM_DB_PASSWORD", ""),
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
    out: Dict[str, List[str]] = {}
    for r in query(crm, "SELECT category_code, document_search_plan FROM crm_product_categories WHERE is_active"):
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


def _index_dir(task_dir: Path) -> Dict[str, Path]:
    idx: Dict[str, Path] = {}
    if not task_dir.exists():
        return idx
    for p in task_dir.rglob("*"):
        if p.is_file():
            idx.setdefault(p.name.strip().lower(), p)
            idx.setdefault(p.stem.strip().lower(), p)
    return idx


def _match(idx: Dict[str, Path], wanted: str) -> Optional[Path]:
    key = (wanted or "").strip().lower()
    if not key:
        return None
    if key in idx:
        return idx[key]
    stem = Path(key).stem
    if stem in idx:
        return idx[stem]
    for k, p in idx.items():
        if k and (k.startswith(stem) or stem.startswith(k)):
            return p
    return None


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        vocab = category_keywords(crm)
        lane = query(
            di,
            "SELECT id, procurement_id, status, selected_documents FROM document_processing_queue"
            " WHERE queue_lane=%s ORDER BY id",
            (LANE,),
        )
        factory = ParserFactory()
        c = Counter()
        per_cat = defaultdict(Counter)
        fails = Counter()
        for row in lane:
            qid = int(row["id"])
            pid = int(row["procurement_id"])
            docs = row.get("selected_documents") or []
            c["QUEUE_ROWS"] += 1
            idx = _index_dir(DOWNLOAD_ROOT / str(qid))
            if not idx:
                c["TASKDIR_EMPTY"] += 1
                continue
            for entry in docs:
                sid = entry.get("source_document_id")
                fname = entry.get("file_name") or ""
                category = entry.get("category") or "unknown"
                path = _match(idx, fname)
                if path is None:
                    c["SELECTED_FILE_NOT_IN_TASKDIR"] += 1
                    continue
                c["DOCS_SELECTED"] += 1
                if category == "unknown":
                    c["UNKNOWN_CATEGORY"] += 1
                facts = []
                try:
                    if path.suffix.lower() in {".xlsx", ".xlsm"}:
                        rows = read_xlsx_facts(path)
                        facts = facts_from_table_rows(
                            procurement_id=pid, category_code=category, document_name=fname,
                            rows=rows, source_document_id=int(sid) if sid is not None else None,
                            category_keywords=vocab.get(category, []),
                        )
                    else:
                        parser = get_rich_parser(factory, path) if supports_rich_meta(path) else factory.get_parser(path)
                        if parser is None:
                            c["FILES_FAILED"] += 1
                            fails["unsupported_format"] += 1
                            continue
                        text, line_meta = parse_file_with_meta(parser, path)
                        facts = extract_facts(
                            procurement_id=pid, category_code=category, document_name=fname,
                            text=text, line_meta=line_meta,
                            source_document_id=int(sid) if sid is not None else None,
                            category_keywords=vocab.get(category, []),
                        )
                except Exception as exc:
                    c["FILES_FAILED"] += 1
                    fails["parser_failure"] += 1
                    continue
                c["FILES_PARSED"] += 1
                if facts:
                    c["FILES_WITH_FACTS"] += 1
                    created, reused, stats = persist_facts(
                        di, procurement_id=pid, document_name=fname,
                        category_code=category, facts=facts,
                    )
                    c["ENTITIES_CREATED"] += created
                    c["ENTITIES_REUSED"] += reused
                    for k, v in stats.items():
                        c[k.upper()] += v
                    for f in facts:
                        per_cat[category]["FACTS"] += 1
                else:
                    c["FILES_WITHOUT_FACTS"] += 1
        di.commit()
        print("=" * 78)
        print("TIER0 EXTRACTION FROM TASK DIRS (HTTP=0)")
        for k in (
            "QUEUE_ROWS", "TASKDIR_EMPTY", "DOCS_SELECTED", "SELECTED_FILE_NOT_IN_TASKDIR",
            "FILES_PARSED", "FILES_FAILED", "FILES_WITH_FACTS", "FILES_WITHOUT_FACTS",
            "ENTITIES_CREATED", "ENTITIES_REUSED", "MATERIAL", "QUANTITY", "UNIT",
            "UNIT_PRICE", "TOTAL", "WITH_CATEGORY", "UNKNOWN_CATEGORY", "WITHOUT_PROVENANCE",
        ):
            print(f"{k}={c.get(k, 0)}")
        print(f"FAIL_REASONS={dict(fails)}")
        print(f"PER_CATEGORY={ {k: dict(v) for k, v in sorted(per_cat.items())} }")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
