#!/usr/bin/env python3
"""Read-only check of the deterministic section detector (SECTION_LEVEL_NORMALIZATION_V1).

Runs `SectionTracker` over the stored `structured_extraction_runs` snapshots of one
procurement and reports the detected sections, their children and totals.

No DB writes. Run with the document-contour venv + env:

    cd /opt/tender_documents_research && set -a && . /opt/CRM_Streamlit/.env; set +a
    /opt/tender_documents_research/.venv/bin/python /opt/CRM_Streamlit/scripts/audit_section_detector.py --procurement-id 148391
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Iterable, Iterator, Optional, Tuple

import psycopg2

# Snapshot quotes are a cell dump ("A=… | B=…"); the extractor sees bare cell
# texts, so strip the column prefix before the detector looks at a cell.
_CELL_PREFIX = re.compile(r"^[A-Z]{1,3}=")


def _cells_of(quote: str) -> list:
    return [p.strip() for p in quote.split("|") if p.strip()]


def _strip_prefix(cells: list) -> list:
    return [_CELL_PREFIX.sub("", c).strip() for c in cells]


def di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def iter_rows(snapshot: Optional[str]) -> Iterator[Tuple[Optional[str], str, list, Optional[float]]]:
    """Yield (sheet, row_text, cells, row_total) from a stored snapshot."""
    try:
        data = json.loads(snapshot or "[]")
    except Exception:
        return
    if not isinstance(data, list):
        return
    for item in data:
        if isinstance(item, dict):
            quote = item.get("source_quote") or ""
            cells = _strip_prefix(_cells_of(str(quote)))
            total = item.get("total_price_value")
            try:
                total = float(total) if total is not None else None
            except (TypeError, ValueError):
                total = None
            yield item.get("sheet"), str(quote), cells, total
        elif isinstance(item, str):
            cells = _strip_prefix(_cells_of(item))
            yield None, item, cells, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procurement-id", type=int, default=148391)
    args = ap.parse_args()

    from document_processor.section_detector import SectionTracker

    conn = di_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, source_text_snapshot FROM structured_extraction_runs"
            " WHERE procurement_id = %s ORDER BY id",
            (args.procurement_id,),
        )
        tracker = SectionTracker()
        residue_rows = 0
        for run_id, snapshot in cur.fetchall():
            rows = 0
            for sheet, text, cells, total in iter_rows(snapshot):
                rows += 1
                code = tracker.observe(sheet, cells, text)
                if code is None:
                    residue_rows += 1
                else:
                    tracker.add_child(code, total)
            print(f"run {run_id}: rows={rows}")
        sections = tracker.finalize()
        print(f"sections={len(sections)} residue_rows={residue_rows}")
        for info in sections:
            print(
                f"  {info.code} | name={info.name} | sheet={info.sheet}"
                f" | children={info.children} | computed={round(info.computed_sum, 2)}"
                f" | total={info.total_value} | source={info.total_source}"
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
