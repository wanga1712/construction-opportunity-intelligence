#!/usr/bin/env python3
"""Backfill quantity/unit/price for lighting estimate rows where price+total prove quantity."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg2

CRM_ROOT = "/opt/CRM_Streamlit"
sys.path.insert(0, CRM_ROOT)


def _di_conn():
    import os
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def _parse_cells(quote: str) -> dict[str, str]:
    cells = {}
    for part in str(quote or "").split("|"):
        part = part.strip()
        if len(part) > 2 and part[1] == "=" and part[0].isalpha():
            cells[part[0].upper()] = part[2:].strip()
    return cells


def _num(value: str):
    if not value:
        return None
    s = value.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    import os
    import sys

    if len(sys.argv) < 2:
        print("usage: repair_lighting_estimate_facts.py <procurement_id>")
        return 2
    pid = int(sys.argv[1])
    conn = _di_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_quote, product_name_raw
                  FROM structured_entities
                 WHERE procurement_id=%s
                   AND category_code='lighting'
                   AND quantity_value IS NULL
                """,
                (pid,),
            )
            rows = cur.fetchall()
        updated = 0
        with conn.cursor() as cur:
            for row_id, quote, name in rows:
                cells = _parse_cells(quote)
                unit = cells.get("D") or cells.get("C")
                price = _num(cells.get("F"))
                total = _num(cells.get("G"))
                if not unit or price is None or total is None or price <= 0:
                    continue
                qty = total / price
                if abs(qty - round(qty)) > 0.02:
                    continue
                qty = float(round(qty))
                cur.execute(
                    """
                    UPDATE structured_entities
                       SET quantity_value=%s,
                           quantity_raw=%s,
                           quantity_unit_raw=%s,
                           quantity_unit_normalized='PCS',
                           unit_price_value=%s,
                           unit_price_raw=%s,
                           total_price_value=%s,
                           total_price_raw=%s,
                           layout_status='CONSISTENT'
                     WHERE id=%s
                    """,
                    (
                        qty, str(qty), unit, price, str(price), total, str(total),
                        row_id,
                    ),
                )
                updated += cur.rowcount
        conn.commit()
        print(f"PROCUREMENT={pid} UPDATED={updated}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
