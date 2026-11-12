#!/usr/bin/env python3
"""Repair GrandSmeta quantities/prices from arithmetic-proven source quotes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

for root in ("/opt/CRM_Streamlit", "/opt/tender_documents_research"):
    if root not in sys.path:
        sys.path.insert(0, root)

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=True)

from document_processor.estimate_value_mapping import find_arithmetic_triple
from document_processor.parse_extractors import _connect as connect_document_db
from document_processor.smeta_forma_4b import _num

_CELL_RE = re.compile(r"(?:^|\s*\|\s*)([A-Z]+)=([^|]*)")


def _plan_hash(plan: list[dict[str, Any]]) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _quoted_numbers(source_quote: str) -> tuple[list[tuple[str, float]], dict[str, str]]:
    numbers: list[tuple[str, float]] = []
    raw_by_label: dict[str, str] = {}
    quote = str(source_quote or "")
    for label, raw in _CELL_RE.findall(quote):
        raw = raw.strip()
        value = _num(raw)
        if value is not None:
            numbers.append((label, value))
            raw_by_label[label] = raw
    if not numbers:
        # Some extracted quotes preserve table cells without coordinates.
        for index, raw in enumerate(part.strip() for part in quote.split("|")):
            value = _num(raw)
            if value is not None:
                label = f"TOKEN_{index}"
                numbers.append((label, value))
                raw_by_label[label] = raw
    return numbers, raw_by_label


def _preferred_grand_smeta_match(
    numbers: list[tuple[str, float]],
) -> tuple[str, float, str, float, str, float, float] | None:
    """Prefer known current-price columns over arbitrary arithmetic triples."""
    by_label = dict(numbers)
    for qty_label, price_label, total_label in (
        ("O", "U", "X"),
        ("P", "V", "Y"),
    ):
        if all(label in by_label for label in (qty_label, price_label, total_label)):
            quantity = by_label[qty_label]
            price = by_label[price_label]
            total = by_label[total_label]
            denominator = max(abs(total), abs(quantity * price), 1.0)
            delta = abs(total - quantity * price) / denominator
            if delta <= 0.05:
                return (
                    qty_label,
                    quantity,
                    price_label,
                    price,
                    total_label,
                    total,
                    delta,
                )
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--procurement-ids", required=True)
    parser.add_argument("--category-code")
    parser.add_argument("--match-name")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument(
        "--report",
        default="/tmp/grand_smeta_quote_arithmetic.json",
    )
    parser.add_argument(
        "--preimage",
        default="/tmp/grand_smeta_quote_arithmetic_preimage.json",
    )
    args = parser.parse_args()
    if args.apply and not args.expected_plan_sha256:
        raise SystemExit("--expected-plan-sha256 is required with --apply")

    pids = sorted(
        {
            int(value)
            for value in str(args.procurement_ids).split(",")
            if value.strip()
        }
    )
    conn = connect_document_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where = """
                 WHERE procurement_id = ANY(%s)
                   AND row_kind = 'GOODS'
            """
            params: list[Any] = [pids]
            if args.category_code:
                where += " AND category_code = %s"
                params.append(args.category_code)
            if args.match_name:
                where += " AND name_raw ILIKE %s"
                params.append(f"%{args.match_name}%")
            cur.execute(
                """
                SELECT id, procurement_id, row_ref, name_raw, quantity_raw,
                       quantity_value, unit_raw, unit_price_raw, unit_price_value,
                       total_raw, total_value, layout_status, source_quote
                  FROM structured_estimate_rows
                """
                + where
                + """
                 ORDER BY id
                """,
                tuple(params),
            )
            rows = [dict(row) for row in cur.fetchall()]

        plan: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for row in rows:
            numbers, raw_by_label = _quoted_numbers(str(row["source_quote"] or ""))
            match = _preferred_grand_smeta_match(numbers)
            if match is None:
                match = find_arithmetic_triple(numbers)
            if match is None:
                unresolved.append(
                    {
                        "id": row["id"],
                        "row_ref": row["row_ref"],
                        "reason": "no_arithmetic_triple",
                    }
                )
                continue
            qty_label, quantity, price_label, price, total_label, total, delta = match
            target = {
                "quantity_raw": raw_by_label[qty_label],
                "quantity_value": Decimal(str(quantity)),
                "unit_price_raw": raw_by_label[price_label],
                "unit_price_value": Decimal(str(price)),
                "total_raw": raw_by_label[total_label],
                "total_value": Decimal(str(total)),
                "layout_status": "CONSISTENT",
            }
            before = {
                key: row[key]
                for key in (
                    "quantity_raw",
                    "quantity_value",
                    "unit_price_raw",
                    "unit_price_value",
                    "total_raw",
                    "total_value",
                    "layout_status",
                )
            }
            if any(before[key] != target[key] for key in target):
                plan.append(
                    {
                        "id": int(row["id"]),
                        "row_ref": row["row_ref"],
                        **target,
                        "source_columns": {
                            "quantity": qty_label,
                            "unit_price": price_label,
                            "total": total_label,
                        },
                        "arithmetic_delta": delta,
                        "before": before,
                    }
                )

        digest = _plan_hash(plan)
        if plan:
            Path(args.preimage).write_text(
                json.dumps(plan, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        if args.apply:
            if digest != args.expected_plan_sha256:
                raise SystemExit(f"plan hash mismatch: {digest}")
            with conn.cursor() as cur:
                psycopg2.extras.execute_batch(
                    cur,
                    """
                    UPDATE structured_estimate_rows
                       SET quantity_raw = %s,
                           quantity_value = %s,
                           unit_price_raw = %s,
                           unit_price_value = %s,
                           total_raw = %s,
                           total_value = %s,
                           layout_status = %s,
                           updated_at = NOW()
                     WHERE id = %s
                    """,
                    [
                        (
                            item["quantity_raw"],
                            item["quantity_value"],
                            item["unit_price_raw"],
                            item["unit_price_value"],
                            item["total_raw"],
                            item["total_value"],
                            item["layout_status"],
                            item["id"],
                        )
                        for item in plan
                    ],
                    page_size=100,
                )
            conn.commit()
        else:
            conn.rollback()
        report = {
            "status": "APPLIED" if args.apply else "DRY_RUN",
            "plan_sha256": digest,
            "procurement_ids": pids,
            "category_code": args.category_code,
            "match_name": args.match_name,
            "rows_scanned": len(rows),
            "planned_updates": len(plan),
            "unresolved": unresolved,
            "plan": plan,
        }
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "status",
                        "plan_sha256",
                        "rows_scanned",
                        "planned_updates",
                        "unresolved",
                    )
                },
                ensure_ascii=False,
                default=str,
            )
        )
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
