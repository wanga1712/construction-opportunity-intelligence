#!/usr/bin/env python3
"""Repair existing GrandSmeta rows from an explicitly named source workbook."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
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

from document_processor.parse_extractors import _connect as connect_document_db
from document_processor.xlsx_table_reader import read_tables


def _plan_hash(plan: list[dict[str, Any]]) -> str:
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _extract_member(archive: Path, member: str, target: Path) -> None:
    with target.open("wb") as out:
        subprocess.run(
            ["unrar", "p", "-inul", str(archive), member],
            check=True,
            stdout=out,
        )


def _build_plan(
    conn: Any,
    *,
    procurement_id: int,
    match_name: str,
    facts_by_ref: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, row_ref, name_raw, quantity_raw, quantity_value,
                   unit_price_raw, unit_price_value, total_raw, total_value,
                   layout_status
              FROM structured_estimate_rows
             WHERE procurement_id = %s
               AND name_raw ILIKE %s
             ORDER BY id
            """,
            (procurement_id, f"%{match_name}%"),
        )
        current = [dict(row) for row in cur.fetchall()]

    plan: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in current:
        ref = str(row["row_ref"] or "")
        fact = facts_by_ref.get(ref)
        if fact is None:
            missing.append({"id": row["id"], "row_ref": ref, "reason": "source_row_missing"})
            continue
        target = {
            "quantity_raw": fact.quantity_raw,
            "quantity_value": _decimal(fact.quantity_value),
            "unit_price_raw": fact.unit_price_raw,
            "unit_price_value": _decimal(fact.unit_price_value),
            "total_raw": fact.total_raw,
            "total_value": _decimal(fact.total_price_value),
            "layout_status": fact.layout_status,
        }
        if target["quantity_value"] is None or target["unit_price_value"] is None:
            missing.append({"id": row["id"], "row_ref": ref, "reason": "incomplete_source_row"})
            continue
        if target["total_value"] is None:
            expected = target["quantity_value"] * target["unit_price_value"]
            if expected <= 0:
                missing.append({"id": row["id"], "row_ref": ref, "reason": "no_total"})
                continue
            target["total_value"] = expected
            target["total_raw"] = str(expected)
        if any(row[key] != target[key] for key in target):
            plan.append(
                {
                    "id": int(row["id"]),
                    "row_ref": ref,
                    **target,
                    "before": {
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
                    },
                }
            )
    return plan, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--procurement-id", type=int, required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--match-name", required=True)
    parser.add_argument("--expected-rows", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument(
        "--report",
        default="/tmp/grand_smeta_source_backfill.json",
    )
    parser.add_argument(
        "--preimage",
        default="/tmp/grand_smeta_source_backfill_preimage.json",
    )
    args = parser.parse_args()
    if args.apply and not args.expected_plan_sha256:
        raise SystemExit("--expected-plan-sha256 is required with --apply")

    archive = Path(args.archive)
    conn = connect_document_db()
    try:
        with tempfile.TemporaryDirectory(prefix="grand-smeta-") as temp:
            workbook = Path(temp) / "source.xlsx"
            _extract_member(archive, args.member, workbook)
            facts = [
                fact
                for fact in read_tables(workbook, include_descriptive=False)
                if args.match_name.lower() in fact.product_name_raw.lower()
            ]
        facts_by_ref = {str(fact.row): fact for fact in facts}
        if len(facts_by_ref) != args.expected_rows:
            raise SystemExit(
                f"source row count mismatch: {len(facts_by_ref)} != {args.expected_rows}"
            )
        plan, missing = _build_plan(
            conn,
            procurement_id=args.procurement_id,
            match_name=args.match_name,
            facts_by_ref=facts_by_ref,
        )
        digest = _plan_hash(plan)
        if missing:
            raise SystemExit(json.dumps({"missing": missing}, ensure_ascii=False))
        if len(plan) > 0:
            Path(args.preimage).write_text(
                json.dumps(plan, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        if args.apply and plan:
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
            "procurement_id": args.procurement_id,
            "source_rows": len(facts_by_ref),
            "planned_updates": len(plan),
            "missing": missing,
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
                        "source_rows",
                        "planned_updates",
                        "missing",
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
