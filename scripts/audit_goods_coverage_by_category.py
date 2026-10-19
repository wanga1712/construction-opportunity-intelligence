#!/usr/bin/env python3
"""GOOD_SUPPLY_FACTS_V1 Phase 0.1 — почему категория даёт 0-5 goods-фактов.

Read-only матрица по категориям:
  * trust state, layout_status, entity_type;
  * classify_fact_kind (GOODS/WORK/...);
  * причины отсева classify_supply_row
    (no_quote / no_category / work / aggregate / no_quantity / no_total);
  * примеры строк для каждой причины.

DB_WRITES=0. Ничего не меняет.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.good_supply_facts_service import classify_supply_row  # noqa: E402
from src.services.works_vs_goods_service import classify_fact_kind  # noqa: E402

DEFAULT_CATEGORIES = (
    "curbstone",
    "drainage_water_management",
    "flooring",
    "cable_support_systems",
    "lighting",
)

SQL = """
SELECT procurement_id, category_code, entity_type,
       product_name_raw, product_name_normalized,
       quantity_value, quantity_unit_raw, quantity_unit_normalized,
       unit_price_value, total_price_value, source_quote,
       row_or_line, page_or_sheet, layout_status,
       structured_fact_trust_state, extractor_version
  FROM structured_entities
 WHERE category_code = %s
"""


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


def _kind(row: Dict[str, Any]) -> str:
    try:
        return classify_fact_kind(
            entity_type=row.get("entity_type"),
            name=row.get("product_name_normalized") or row.get("product_name_raw"),
        )
    except Exception:
        return "ERROR"


def _reason(row: Dict[str, Any]) -> str:
    try:
        return classify_supply_row(row) or "OK"
    except Exception:
        return "ERROR"


def _sample(row: Dict[str, Any]) -> str:
    return (
        f'name="{str(row.get("product_name_raw") or "")[:60]}" '
        f'layout={row.get("layout_status")} qty={row.get("quantity_value")} '
        f'unit={row.get("quantity_unit_normalized")} '
        f'total={row.get("total_price_value")} '
        f'trust={row.get("structured_fact_trust_state")}'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES))
    args = ap.parse_args()
    cats = [c.strip() for c in args.categories.split(",") if c.strip()]

    conn = psycopg2.connect(**di_dsn())
    try:
        for cat in cats:
            rows = query(conn, SQL, (cat,))
            total = len(rows)
            print("=" * 78)
            print(f"CATEGORY={cat} TOTAL={total}")
            if not total:
                continue
            trust = Counter(r.get("structured_fact_trust_state") or "<null>" for r in rows)
            layout = Counter(r.get("layout_status") or "<null>" for r in rows)
            annotated = [(r, _reason(r), _kind(r)) for r in rows]
            kinds = Counter(kind for _, _, kind in annotated)
            reasons = Counter(reason for _, reason, _ in annotated)
            has_qty = sum(1 for r in rows if r.get("quantity_value") is not None)
            has_unit = sum(1 for r in rows if r.get("quantity_unit_normalized"))
            has_total = sum(1 for r in rows if r.get("total_price_value") is not None)
            trusted = [r for r in rows if r.get("structured_fact_trust_state") == "TRUSTED_PRODUCTION"]
            trusted_goods = [r for r in trusted if _kind(r) == "GOODS"]
            trusted_goods_qty_unit = [
                r for r in trusted_goods
                if r.get("quantity_value") is not None and r.get("quantity_unit_normalized")
            ]
            trusted_goods_full = [
                r for r in trusted_goods_qty_unit if r.get("total_price_value") is not None
            ]
            print(f"  trust={dict(trust)}")
            print(f"  layout={dict(layout)}")
            print(f"  kind={dict(kinds)}")
            print(f"  reject={dict(reasons)}")
            print(
                f"  has_qty={has_qty} has_unit={has_unit} has_total={has_total} "
                f"trusted={len(trusted)} trusted_goods={len(trusted_goods)} "
                f"trusted_goods_qty_unit={len(trusted_goods_qty_unit)} "
                f"trusted_goods_full={len(trusted_goods_full)}"
            )
            print("  samples:")
            for reason in ("work", "no_quantity", "no_total", "aggregate", "no_quote", "OK"):
                items = [r for r, reason_, _ in annotated if reason_ == reason]
                if not items:
                    continue
                print(f"    [{reason}] n={len(items)}")
                for r in items[:2]:
                    print(f"      {_sample(r)}")
    finally:
        conn.close()
    print("=" * 78)
    print("DB_WRITES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
