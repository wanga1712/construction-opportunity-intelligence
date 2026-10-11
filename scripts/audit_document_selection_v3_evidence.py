#!/usr/bin/env python3
"""DOCUMENT_SELECTION_V3 - PHASE 2 evidence audit (read-only).

Takes the CURRENT (procurement, category) units whose every historical
known-positive document is skip-listed (the "158 conflict") and classifies each
unit's stored evidence as:

    TRUE_COMMERCIAL_EVIDENCE - the file really carries commercial facts
                               (material/product, characteristic, quantity,
                               unit, specification, volume, price);
    CONTEXT_ONLY             - only category/context mention, no commercial facts;
    FALSE_POSITIVE           - validation says the match is not real;
    UNVERIFIABLE             - no stored quote/fragment to decide.

No writes anywhere. Report drives the Phase 4 soft-fallback priority.
"""

from __future__ import annotations

import os
import re
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
if Path(DOC_RUNTIME).exists() and DOC_RUNTIME not in sys.path:
    sys.path.insert(0, DOC_RUNTIME)

from src.services.commercial_routing_v3.document_needs_plan_v2 import (  # noqa: E402
    HARD_SKIP,
    SOFT_SKIP,
    classify_skip_policy,
    soft_skip_class,
)
from document_processor.file_skip_list import should_skip_file  # noqa: E402


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


CURRENT_SQL = """
SELECT o.procurement_id, o.commercial_category_code AS category_code,
       o.opportunity_track, o.candidate_initial_medal,
       c.category_name
  FROM crm_procurement_category_opportunities o
  LEFT JOIN crm_product_categories c
         ON c.category_code = o.commercial_category_code
 WHERE o.status = 'CURRENT'
"""

KP_SQL = """
SELECT DISTINCT m.procurement_id, d.category_code, m.document_name
  FROM document_match_details d
  JOIN document_matches m ON m.id = d.match_id
 WHERE m.document_name IS NOT NULL
   AND m.procurement_id = ANY(%s)
"""

EVIDENCE_SQL = """
SELECT m.procurement_id, d.category_code, m.document_name,
       d.matched_term, d.term_type, d.score, d.match_method,
       d.validation_status, d.matched_text, d.rule_term, d.page_or_sheet,
       d.row_data, d.context_before, d.context_after, d.document_id
  FROM document_match_details d
  JOIN document_matches m ON m.id = d.match_id
 WHERE m.procurement_id = ANY(%s)
   AND m.document_name IS NOT NULL
"""

DOC_IDS_SQL = """
SELECT procurement_id, file_name, min(id) AS source_document_id
  FROM document_files
 WHERE procurement_id = ANY(%s)
 GROUP BY procurement_id, file_name
"""

#: Commercial fact markers. A bare category mention is deliberately not enough.
UNIT_RE = re.compile(
    r"\d[\d\s.,]*\s*(шт|м2|м²|м3|м³|кг|т|л|мм|см|м\b|пог\.?\s?м|компл|рулон|упак|меш|лист|пачк)"
)
COMMERCIAL_WORDS = (
    "характеристик",
    "спецификац",
    "материал",
    "товар",
    "количество",
    "единиц",
    "объем",
    "объём",
    "цена",
    "стоимость",
    "масса",
    "диаметр",
    "толщин",
    "марка",
    "артикул",
    "модель",
)
INVALID_STATUS = {"INVALID", "FALSE", "FALSE_POSITIVE", "REJECTED", "NOT_FOUND"}

TRUE_COMMERCIAL_EVIDENCE = "TRUE_COMMERCIAL_EVIDENCE"
CONTEXT_ONLY = "CONTEXT_ONLY"
FALSE_POSITIVE = "FALSE_POSITIVE"
UNVERIFIABLE = "UNVERIFIABLE"


def _blob(row: Dict[str, Any]) -> str:
    parts = [
        row.get("matched_term"),
        row.get("matched_text"),
        row.get("rule_term"),
        str(row.get("row_data")) if row.get("row_data") else None,
        str(row.get("context_before")) if row.get("context_before") else None,
        str(row.get("context_after")) if row.get("context_after") else None,
    ]
    return " ".join(str(p) for p in parts if p).lower()


def classify_unit(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return UNVERIFIABLE
    if all((r.get("validation_status") or "").upper() in INVALID_STATUS for r in rows):
        return FALSE_POSITIVE
    has_quote = any(
        r.get("matched_text") or r.get("row_data") or r.get("context_before") or r.get("context_after")
        for r in rows
    )
    if not has_quote:
        return UNVERIFIABLE
    for r in rows:
        blob = _blob(r)
        if UNIT_RE.search(blob) or any(w in blob for w in COMMERCIAL_WORDS):
            return TRUE_COMMERCIAL_EVIDENCE
        term_type = (r.get("term_type") or "").upper()
        if term_type in {"QUANTITY", "UNIT", "UNIT_PRICE", "PRICE", "TABLE_CELL"}:
            return TRUE_COMMERCIAL_EVIDENCE
    return CONTEXT_ONLY


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        opps = query(crm, CURRENT_SQL)
        current_pids = sorted({int(o["procurement_id"]) for o in opps})
        cat_name = {o["category_code"]: o.get("category_name") for o in opps}
        print(f"CURRENT_OPPORTUNITIES={len(opps)} CURRENT_PIDS={len(current_pids)}")

        kp = query(di, KP_SQL, (current_pids,))
        units: Dict[tuple, set] = defaultdict(set)
        for r in kp:
            units[(int(r["procurement_id"]), r["category_code"])].add(r["document_name"])

        audited = {
            key: names
            for key, names in units.items()
            if names and all(should_skip_file(n) for n in names)
        }
        print(f"CURRENT_UNITS_KNOWN_POSITIVE={len(units)}")
        print(f"CURRENT_UNITS_ONLY_IN_SKIP_FILES={len(audited)}")

        audited_pids = sorted({pid for pid, _ in audited})
        evidence = query(di, EVIDENCE_SQL, (audited_pids,))
        docs = {
            (int(r["procurement_id"]), r["file_name"]): int(r["source_document_id"])
            for r in query(di, DOC_IDS_SQL, (audited_pids,))
        }

        ev_by_unit: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
        for r in evidence:
            key = (int(r["procurement_id"]), r["category_code"])
            if key in audited:
                ev_by_unit[key].append(r)

        counts = Counter()
        class_counts = Counter()
        by_soft_class = defaultdict(Counter)
        details = []
        for (pid, category), names in sorted(audited.items()):
            rows = ev_by_unit.get((pid, category), [])
            verdict = classify_unit(rows)
            counts[verdict] += 1
            # Soft class of this unit (the best/softest skip name).
            labels = [soft_skip_class(n) for n in names]
            labels = [l for l in labels if l]
            label = labels[0] if labels else "NONE"
            by_soft_class[label][verdict] += 1
            class_counts[label] += 1
            sample = names and sorted(names)[0]
            details.append(
                {
                    "procurement_id": pid,
                    "category": category,
                    "documents": sorted(names),
                    "soft_class": label,
                    "verdict": verdict,
                    "source_document_id": docs.get((pid, sample)),
                    "evidence_rows": len(rows),
                    "matched_terms": sorted(
                        {str(r.get("matched_term")) for r in rows if r.get("matched_term")}
                    )[:5],
                }
            )

        total = len(audited)
        print("=" * 78)
        print("PHASE 2 - CURRENT EVIDENCE AUDIT (units existing only in skip files)")
        print(f"AUDITED_CURRENT_UNITS={total}")
        print(f"TRUE_COMMERCIAL_EVIDENCE={counts[TRUE_COMMERCIAL_EVIDENCE]}")
        print(f"CONTEXT_ONLY={counts[CONTEXT_ONLY]}")
        print(f"FALSE_POSITIVE={counts[FALSE_POSITIVE]}")
        print(f"UNVERIFIABLE={counts[UNVERIFIABLE]}")
        for label in (
            "PROJECT_CONTRACT",
            "NOTICE",
            "ELECTRONIC_AUCTION",
            "PRINTED_CONTRACT_FORM",
            "CONTRACT_FORM_OTHER",
            "CONTRACT_INFO",
            "SOFT_OTHER",
            "NONE",
        ):
            n = class_counts.get(label, 0)
            if not n:
                continue
            true_n = by_soft_class[label].get(TRUE_COMMERCIAL_EVIDENCE, 0)
            print(
                f"{label}: units={n} true={true_n} true_rate={(100.0 * true_n / n):.1f}% "
                f"context={by_soft_class[label].get(CONTEXT_ONLY, 0)} "
                f"false={by_soft_class[label].get(FALSE_POSITIVE, 0)} "
                f"unverifiable={by_soft_class[label].get(UNVERIFIABLE, 0)}"
            )
        print("=" * 78)
        print("AUDIT_DETAILS_BEGIN")
        for d in details:
            print(
                f"PID={d['procurement_id']} CAT={d['category']} SOFT={d['soft_class']} "
                f"VERDICT={d['verdict']} SRC_DOC_ID={d['source_document_id']} "
                f"ROWS={d['evidence_rows']} DOCS={d['documents'][:3]} "
                f"TERMS={d['matched_terms']}"
            )
        print("AUDIT_DETAILS_END")
    finally:
        crm.close()
        di.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
