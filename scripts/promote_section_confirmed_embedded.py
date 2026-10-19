#!/usr/bin/env python3
"""GOOD_SUPPLY_FACTS_V1 Phase 1 — SECTION_CONFIRMED trust path для EMBEDDED.

Промоутит только EMBEDDED-факты (не DIRECT_CATS), которые одновременно:

  * section_code IS NOT NULL (и не RESIDUE);
  * section_total_source IN ('SECTION_TOTAL', 'COMPUTED_SUM');
  * canonical goods predicate пройден (PRODUCT + CONSISTENT + qty/unit,
    unit не денежный, имя не агрегат, classify_fact_kind == GOODS);
  * source_quote literal-verified в structured_extraction_runs.source_text_snapshot;
  * сейчас MANUAL_PROOF_QUARANTINE.

Default: dry-run (DB_WRITES=0). `--apply` пишет trust state; запускать только
после отдельного approval.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
for p in (ROOT, ROOT / "tender_documents_research", ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import audit_estimate_first_confirmation as audit  # noqa: E402
from build_confirmed_facts import semantic_key  # noqa: E402
from src.services.works_vs_goods_service import classify_fact_kind  # noqa: E402
from document_processor.section_detector import is_summarizable  # noqa: E402

DIRECT_CATS = ("computers", "lighting", "cable_support_systems")
SECTION_CONFIRMED = "SECTION_CONFIRMED"
ALLOWED_TOTAL_SOURCES = ("SECTION_TOTAL", "COMPUTED_SUM")


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params=None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


_BASE_SELECT = """
SELECT se.id, se.run_id, se.procurement_id, se.category_code,
       se.source_document_id, se.physical_download_key,
       se.entity_type, se.product_name_raw, se.product_name_normalized,
       se.quantity_value, se.quantity_unit_raw, se.quantity_unit_normalized,
       se.unit_price_value, se.total_price_value, se.source_quote,
       se.row_or_line, se.page_or_sheet, se.layout_status,
       se.section_code, se.section_name, se.section_total_source,
       se.structured_fact_trust_state
  FROM structured_entities se
"""

_BASE_FILTER = """
 WHERE se.category_code IS NOT NULL
   AND se.category_code <> 'unknown'
   AND se.category_code <> ALL(%s)
   AND se.structured_fact_trust_state = 'MANUAL_PROOF_QUARANTINE'
   AND se.section_code IS NOT NULL
   AND btrim(se.section_code) <> ''
   AND upper(btrim(se.section_code)) <> 'RESIDUE'
   AND se.section_total_source IN %s
   AND coalesce(se.source_quote, '') <> ''
 ORDER BY se.id
"""

CANDIDATES_SQL_STRICT = (
    _BASE_SELECT
    + " JOIN structured_extraction_runs r ON r.id = se.run_id"
    + _BASE_FILTER.replace(
        "ORDER BY se.id",
        " AND r.source_text_snapshot IS NOT NULL"
        " AND position(se.source_quote in r.source_text_snapshot) > 0"
        " ORDER BY se.id",
    )
)

#: Только для диагностики: показывает потенциал без snapshot-проверки.
CANDIDATES_SQL_RELAXED = _BASE_SELECT + _BASE_FILTER


def _canonical_goods(row: Dict[str, Any]) -> bool:
    if classify_fact_kind(
        entity_type=row.get("entity_type"),
        name=row.get("product_name_normalized") or row.get("product_name_raw"),
    ) != "GOODS":
        return False
    return is_summarizable(
        entity_type=row.get("entity_type"),
        layout_status=row.get("layout_status"),
        quantity_value=row.get("quantity_value"),
        unit_normalized=row.get("quantity_unit_normalized"),
        name=row.get("product_name_normalized") or row.get("product_name_raw"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--diagnostic-skip-snapshot-check",
        action="store_true",
        help="диагностика: не проверять literal snapshot (source_quote всё равно непустой)",
    )
    args = ap.parse_args()

    sql = CANDIDATES_SQL_RELAXED if args.diagnostic_skip_snapshot_check else CANDIDATES_SQL_STRICT
    di = psycopg2.connect(**di_dsn())
    try:
        rows = query(di, sql, (list(DIRECT_CATS), ALLOWED_TOTAL_SOURCES))
    finally:
        di.close()

    canonical = [r for r in rows if _canonical_goods(r)]
    by_cat = Counter(r["category_code"] for r in canonical)
    distinct_units = {(int(r["procurement_id"]), r["category_code"]) for r in canonical}

    # Collapse semantic duplicates exactly как build_confirmed_facts.
    collapsed: Dict[str, Dict[str, Any]] = {}
    for r in canonical:
        collapsed.setdefault(semantic_key(r), r)
    facts = list(collapsed.values())
    agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"facts": 0, "qty": 0, "vrows": 0, "vsum": 0.0}
    )
    for r in facts:
        a = agg[(int(r["procurement_id"]), r["category_code"])]
        a["facts"] += 1
        if r.get("quantity_value") is not None and r.get("quantity_unit_normalized"):
            a["qty"] += 1
        if r.get("total_price_value") is not None:
            a["vrows"] += 1
            a["vsum"] += float(r["total_price_value"])

    # Medal projection by the existing authority formula.
    crm = psycopg2.connect(**audit.crm_dsn())
    try:
        opps = query(crm, """
            SELECT o.id, o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state, o.candidate_initial_medal,
                   o.confirmed_base_medal, p.execution_end_at, p.delivery_end_date, p.end_date
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
    finally:
        crm.close()

    cohort: Dict[str, List[float]] = defaultdict(list)
    for (pid, cat), a in agg.items():
        if a["vrows"]:
            cohort[cat].append(float(a["vsum"]))

    projected_medals: Counter = Counter()
    new_or_changed = 0
    for o in opps:
        key = (int(o["procurement_id"]), o["category_code"])
        a = agg.get(key)
        if not a:
            continue
        score = audit._score(o, a, cohort[o["category_code"]])
        medal = audit.medal_for(score)
        projected_medals[medal] += 1
        if o.get("confirmed_base_medal") != medal:
            new_or_changed += 1

    print("SECTION_CONFIRMED_PROMOTION=DRY_RUN" if not args.apply else "SECTION_CONFIRMED_PROMOTION=APPLY")
    print(f"EMBEDDED_CATEGORIES={sorted({r['category_code'] for r in rows})}")
    print(
        "QUOTE_SNAPSHOT_CHECK="
        + ("SKIPPED_DIAGNOSTIC" if args.diagnostic_skip_snapshot_check else "LITERAL_REQUIRED")
    )
    print(f"QUARANTINE_WITH_SECTION_TOTAL_SOURCE={len(rows)}")
    print(f"CANONICAL_GOODS={len(canonical)}")
    print(f"SEMANTIC_DEDUP_FACTS={len(facts)}")
    print(f"DISTINCT_PROCUREMENT_CATEGORY_UNITS={len(distinct_units)}")
    print(f"OPPORTUNITIES_PROJECTED_WITH_FACTS={sum(projected_medals.values())}")
    print(f"CONFIRMED_BASE_NEW_OR_CHANGED={new_or_changed}")
    print(f"PROJECTED_CONFIRMED_BASE_DISTRIBUTION={dict(projected_medals)}")
    print("BY_CATEGORY (canonical goods, before dedup):")
    for cat, n in by_cat.most_common():
        print(f"  {cat}: {n}")
    if not args.apply:
        print("DB_WRITES=0")
        print("APPLY_NOT_RUN=YES (требуется отдельный approval)")
        return 0

    ids = [int(r["id"]) for r in facts]
    conn = psycopg2.connect(**di_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE structured_entities SET structured_fact_trust_state=%s"
                " WHERE id = ANY(%s) AND structured_fact_trust_state='MANUAL_PROOF_QUARANTINE'",
                (SECTION_CONFIRMED, ids),
            )
            promoted = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    print(f"SECTION_CONFIRMED_PROMOTED={promoted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
