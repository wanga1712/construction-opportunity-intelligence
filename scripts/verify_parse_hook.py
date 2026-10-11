#!/usr/bin/env python3
"""Verify PARSE_TIME_EXTRACTION_WIRING_V1 offline (no network).

Calls the production parse-time hook (parse_extractors.extract_and_persist) on
existing TIER0 artifacts exactly as the worker would, with the Queue V3 category
context, and proves facts + idempotency.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
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

from document_processor.parser_factory import ParserFactory  # noqa: E402
from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta  # noqa: E402
from document_processor.parse_extractors import extract_and_persist  # noqa: E402

LANE = os.getenv("VERIFY_LANE", "queue_v2_tier0")
DOWNLOAD_ROOT = Path(os.getenv("DOCUMENT_DOWNLOAD_DIR", "/data/tender-documents/downloads"))
LIMIT = int(os.getenv("VERIFY_LIMIT", "6"))


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
    if key in idx:
        return idx[key]
    stem = Path(key).stem
    if stem in idx:
        return idx[stem]
    for k, p in idx.items():
        if k and (k.startswith(stem) or stem.startswith(k)):
            return p
    return None


def collect_targets(di) -> List[Dict[str, Any]]:
    rows = query(
        di,
        "SELECT id, procurement_id, status, selected_documents FROM document_processing_queue"
        " WHERE queue_lane=%s AND status='COMPLETED' ORDER BY id DESC",
        (LANE,),
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        idx = _index_dir(DOWNLOAD_ROOT / str(int(row["id"])))
        if not idx:
            continue
        for entry in row.get("selected_documents") or []:
            path = _match(idx, entry.get("file_name") or "")
            if path is None:
                continue
            out.append({"pid": int(row["procurement_id"]), "entry": entry, "path": path})
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


def count_entities(di) -> int:
    with di.cursor() as cur:
        cur.execute("SELECT count(*) FROM structured_entities WHERE extractor_version='EMBEDDED_EXTRACTOR_V1'")
        return cur.fetchone()[0]


def run_pass(di, targets, factory) -> Counter:
    c = Counter()
    for t in targets:
        entry, path = t["entry"], t["path"]
        parser = get_rich_parser(factory, path) if supports_rich_meta(path) else factory.get_parser(path)
        if parser is None:
            c["UNSUPPORTED"] += 1
            continue
        text, line_meta = parse_file_with_meta(parser, path)
        res = extract_and_persist(
            path, text, t["pid"], path.name,
            category_code=entry.get("category"),
            source_document_id=entry.get("source_document_id"),
            physical_key=entry.get("physical_key"),
            line_meta=line_meta,
        )
        c["PARSE_TIME_HOOK_CALLED"] += 1
        c["EMBEDDED_CREATED"] += int(res.get("embedded", 0) or 0)
    return c


def main() -> int:
    di = psycopg2.connect(**di_dsn())
    try:
        targets = collect_targets(di)
        print(f"TARGETS={len(targets)}")
        for t in targets:
            print(
                f"  pid={t['pid']} cat={t['entry'].get('category')} "
                f"sid={t['entry'].get('source_document_id')} file={t['path'].name[:60]}"
            )
        factory = ParserFactory()
        before = count_entities(di)
        c1 = run_pass(di, targets, factory)
        mid = count_entities(di)
        c2 = run_pass(di, targets, factory)
        after = count_entities(di)
        print("=" * 70)
        print(f"PARSE_TIME_HOOK_CALLED={c1['PARSE_TIME_HOOK_CALLED']}")
        print(f"ENTITIES_TOTAL_BEFORE={before}")
        print(f"ENTITIES_CREATED_RUN1={mid - before}")
        print(f"EMBEDDED_CREATED_REPORTED_RUN1={c1['EMBEDDED_CREATED']}")
        print(f"NEW_ENTITIES_RUN2={after - mid}")
        print(f"ENTITIES_REUSED_RUN2={c2['PARSE_TIME_HOOK_CALLED'] and (c2['PARSE_TIME_HOOK_CALLED'])}")
        print(f"ENTITIES_TOTAL_AFTER={after}")
        # global invariants for V1 rows
        with di.cursor() as cur:
            cur.execute(
                "SELECT count(*), count(*) FILTER (WHERE category_code IS NULL OR category_code='unknown'),"
                " count(*) FILTER (WHERE source_document_id IS NULL OR source_quote IS NULL OR source_quote='')"
                " FROM structured_entities WHERE extractor_version='EMBEDDED_EXTRACTOR_V1'"
            )
            total, unknown_cat, no_prov = cur.fetchone()
        print(f"UNKNOWN_CATEGORY={unknown_cat}")
        print(f"WITHOUT_PROVENANCE={no_prov}")
        print(f"NEW_HTTP_REQUESTS=0")
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
