#!/usr/bin/env python3
"""EMBEDDED_ESTIMATE_PARSE_FIRST_V1 — dry-run ПОТЕНЦИАЛА section-шаблонов.

Основной `audit_estimate_first_confirmation.py` читает
`structured_entities.section_code` из БД. Текущие шаблоны (lighting,
curbstone, drainage, flooring, cable_support_systems) проецируют разделы на
чтении и ничего не пишут, поэтому этот скрипт применяет их в памяти и считает
потенциал: сколько goods-фактов попадёт в разделы после backfill/reparse.

Read-only. DB_WRITES=0. Медаль считается той же формулой/порогами, что в
`audit_estimate_first_confirmation.py`.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tender_documents_research") not in sys.path:
    sys.path.insert(0, str(ROOT / "tender_documents_research"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import audit_estimate_first_confirmation as base  # noqa: E402
from src.services.works_vs_goods_service import classify_fact_kind  # noqa: E402
from document_processor.cable_support_systems_section_templates import (
    build_cable_support_sections,
)
from document_processor.curbstone_section_templates import build_curbstone_sections
from document_processor.drainage_section_templates import build_drainage_sections
from document_processor.flooring_section_templates import build_flooring_sections
from document_processor.lighting_section_templates import build_lighting_sections

BUILDERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "lighting": build_lighting_sections,
    "curbstone": build_curbstone_sections,
    "drainage_water_management": build_drainage_sections,
    "flooring": build_flooring_sections,
    "cable_support_systems": build_cable_support_sections,
}

ENTITY_SQL = """
SELECT se.procurement_id, se.category_code, se.source_document_id,
       se.entity_type, se.product_name_raw, se.product_name_normalized,
       se.quantity_value, se.quantity_unit_normalized, se.quantity_unit_raw,
       se.unit_price_value, se.total_price_value, se.source_quote,
       se.row_or_line, se.layout_status, se.page_or_sheet,
       se.structured_fact_trust_state
  FROM structured_entities se
 WHERE se.category_code = ANY(%s)
 ORDER BY se.procurement_id, se.category_code, se.id
"""


def query(conn, sql: str, params=None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def main() -> int:
    crm = psycopg2.connect(**base.crm_dsn())
    di = psycopg2.connect(**base.di_dsn())
    try:
        opps = query(crm, """
            SELECT o.id, o.procurement_id, o.commercial_category_code AS category_code,
                   o.opportunity_track, o.commercial_state, o.candidate_initial_medal,
                   o.confirmed_base_medal, p.execution_end_at, p.delivery_end_date, p.end_date
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
        """)
        rows = query(di, ENTITY_SQL, (list(BUILDERS),))
        db_section_rows = query(di, """
            SELECT procurement_id, category_code, count(*) AS n
              FROM structured_entities
             WHERE structured_fact_trust_state = 'TRUSTED_PRODUCTION'
               AND category_code = ANY(%s)
               AND section_code IS NOT NULL
               AND upper(section_code) <> 'RESIDUE'
               AND entity_type = 'PRODUCT'
             GROUP BY 1, 2
        """, (list(BUILDERS),))
    finally:
        crm.close()
        di.close()

    by_unit: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_unit[(int(r["procurement_id"]), r["category_code"])].append(r)

    # (pid, category) -> {facts, qty, vrows, vsum} по materials внутри разделов
    agg: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"facts": 0, "qty": 0, "vrows": 0, "vsum": 0.0}
    )
    sectioned_by_cat: Counter = Counter()
    total_goods_by_cat: Counter = Counter()
    sections_by_cat: Counter = Counter()
    for (pid, cat), items in by_unit.items():
        builder = BUILDERS[cat]
        result = builder(items)
        sections = result.get("sections") or []
        sections_by_cat[cat] += len(sections)
        for row in items:
            if (
                row.get("structured_fact_trust_state") == "TRUSTED_PRODUCTION"
                and classify_fact_kind(
                    entity_type=row.get("entity_type"),
                    name=row.get("product_name_normalized") or row.get("product_name_raw"),
                ) == "GOODS"
            ):
                total_goods_by_cat[cat] += 1
        for section in sections:
            for m in section.get("materials") or []:
                if m.get("structured_fact_trust_state") != "TRUSTED_PRODUCTION":
                    continue
                if classify_fact_kind(
                    entity_type=m.get("entity_type"),
                    name=m.get("product_name_normalized") or m.get("product_name_raw"),
                ) != "GOODS":
                    continue
                a = agg[(pid, cat)]
                a["facts"] += 1
                sectioned_by_cat[cat] += 1
                if m.get("quantity_value") is not None and m.get("quantity_unit_normalized"):
                    a["qty"] += 1
                if m.get("total_price_value") is not None:
                    a["vrows"] += 1
                    a["vsum"] += float(m["total_price_value"])

    cohort: Dict[str, List[float]] = defaultdict(list)
    for (pid, cat), a in agg.items():
        if a["vrows"]:
            cohort[cat].append(float(a["vsum"]))

    would_keep = would_lose = 0
    db_section_units = {
        (int(r["procurement_id"]), r["category_code"]) for r in db_section_rows
    }
    baseline_keep = baseline_lose = 0
    dist = Counter()
    for o in opps:
        cat = o["category_code"]
        if cat not in BUILDERS:
            continue
        if (int(o["procurement_id"]), cat) in db_section_units:
            baseline_keep += 1
        elif o.get("confirmed_base_medal"):
            baseline_lose += 1
        a = agg.get((int(o["procurement_id"]), cat))
        if not a or not a["facts"]:
            if o.get("confirmed_base_medal"):
                would_lose += 1
            continue
        score = base._score(o, a, cohort[cat])
        dist[base.medal_for(score)] += 1
        would_keep += 1

    total_goods = sum(total_goods_by_cat.values())
    in_section = sum(sectioned_by_cat.values())
    print("ESTIMATE_FIRST_CONFIRMATION_AUDIT=PROJECTED_DRY_RUN")
    print("NOTE=шаблоны применены в памяти; section_code в БД не писался")
    print(f"GOODS_FACTS_TOTAL_PROJECTED={total_goods}")
    print(f"GOODS_FACTS_IN_SECTION_PROJECTED={in_section}")
    print(f"GOODS_FACTS_RESIDUE_PROJECTED={max(0, total_goods - in_section)}")
    print(f"OPPORTUNITIES_WITH_SECTION_FACTS_PROJECTED={would_keep}")
    print(f"CONFIRMED_BASE_WOULD_LOSE_PROJECTED={would_lose}")
    print(f"CONFIRMED_BASE_BASELINE_SAME_CATEGORIES_KEEP={baseline_keep}")
    print(f"CONFIRMED_BASE_BASELINE_SAME_CATEGORIES_LOSE={baseline_lose}")
    print(f"CONFIRMED_BASE_DISTRIBUTION_PROJECTED={dict(dist)}")
    print("BY_CATEGORY:")
    for cat in sorted(BUILDERS):
        total = total_goods_by_cat.get(cat, 0)
        sec = sectioned_by_cat.get(cat, 0)
        pct = (100.0 * sec / total) if total else 0.0
        print(
            f"  {cat}: goods={total} in_section={sec} ({pct:.1f}%) "
            f"sections={sections_by_cat.get(cat, 0)}"
        )
    print("DB_WRITES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
