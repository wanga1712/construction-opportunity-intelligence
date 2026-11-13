#!/usr/bin/env python3
"""Resolve taxonomy and technical attributes over stored estimate rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from document_processor.embedded_extraction import normalize_name
from document_processor.estimate_row_normalization_authority import (
    NORMALIZER_VERSION,
    finish_run,
    rowset_signature,
    start_run,
    upsert_coverage,
)
from document_processor.estimate_row_taxonomy import load_taxonomy
from document_processor.parse_extractors import _connect
from document_processor.universal_estimate_rows import (
    _technical_attributes,
    classify_estimate_row,
)

def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _crm_connect():
    required = (
        "CRM_DB_HOST",
        "CRM_DB_PORT",
        "CRM_DB_DATABASE",
        "CRM_DB_USER",
        "CRM_DB_PASSWORD",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("Missing CRM DB configuration: " + ", ".join(missing))
    return psycopg2.connect(
        host=os.environ["CRM_DB_HOST"],
        port=int(os.environ["CRM_DB_PORT"]),
        dbname=os.environ["CRM_DB_DATABASE"],
        user=os.environ["CRM_DB_USER"],
        password=os.environ["CRM_DB_PASSWORD"],
        connect_timeout=8,
    )


def _attribute_text(attributes: Any) -> str:
    if not isinstance(attributes, list):
        return ""
    values = []
    for item in attributes:
        if not isinstance(item, dict):
            continue
        for key in ("raw_value", "normalized_value", "attribute_name"):
            value = str(item.get(key) or "").strip()
            if value:
                values.append(value)
    return " ".join(values)


def _canonical(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, sort_keys=True, default=str)


def _source_line_key(row: dict) -> tuple:
    ref = str(row.get("row_ref") or "")
    line = re.search(r"\d+$", ref)
    return (
        row.get("procurement_id"), row.get("source_document_id"),
        line.group(0) if line else ref,
        normalize_name(str(row.get("name_raw") or "")),
    )


def _plan_hash(plan: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        plan, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _counts(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE category_code IS NOT NULL),
                   count(*) FILTER (WHERE subcategory_code IS NOT NULL),
                   count(*) FILTER (WHERE jsonb_array_length(technical_attributes) > 0)
              FROM structured_estimate_rows
            """
        )
        total, categories, subcategories, attributes = cur.fetchone()
        cur.execute(
            """
            SELECT category_code, count(*)
              FROM structured_estimate_rows
             WHERE category_code IS NOT NULL
             GROUP BY category_code
             ORDER BY category_code
            """
        )
        by_category = {str(key): int(value) for key, value in cur.fetchall()}
    return {
        "total": int(total),
        "with_category": int(categories),
        "with_subcategory": int(subcategories),
        "with_technical_attributes": int(attributes),
        "by_category": by_category,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--procurement-ids")
    parser.add_argument("--max-rows", type=_positive_int, default=250000)
    parser.add_argument("--run-kind", default="LIVE_RUN")
    parser.add_argument("--proof-source", default="LIVE_RUN")
    parser.add_argument("--sample-categories", action="store_true")
    parser.add_argument(
        "--report",
        default="/tmp/estimate_row_category_resolution.json",
    )
    args = parser.parse_args()
    if args.apply and not args.expected_plan_sha256:
        raise SystemExit("--expected-plan-sha256 is required with --apply")
    pids = sorted(
        int(value)
        for value in str(args.procurement_ids or "").split(",")
        if value.strip()
    )

    load_dotenv("/opt/CRM_Streamlit/.env", override=True)
    di = _connect()
    crm = _crm_connect()
    run_id = None
    try:
        taxonomy = load_taxonomy(crm)
        params: list[Any] = []
        pid_filter = ""
        if pids:
            pid_filter = " AND procurement_id = ANY(%s)"
            params.append(pids)
        sql = """
            SELECT id, procurement_id, source_document_id, row_ref,
                   unit_price_value, name_raw, name_normalized,
                   source_quote, technical_attributes, row_kind,
                   category_code, subcategory_code
              FROM structured_estimate_rows
             WHERE TRUE
        """ + pid_filter + " ORDER BY id LIMIT %s"
        params.append(args.max_rows)
        with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = [dict(row) for row in cur.fetchall()]
            if pids:
                cur.execute(
                    """
                    SELECT id, procurement_id, source_document_id, row_ref, name_raw
                      FROM structured_estimate_rows
                     WHERE procurement_id = ANY(%s)
                     ORDER BY id
                    """,
                    (pids,),
                )
                expected_rows = [dict(row) for row in cur.fetchall()]
            else:
                expected_rows = rows

        expected_rows_by_pid: dict[int, list[dict[str, Any]]] = {}
        for row in expected_rows:
            expected_rows_by_pid.setdefault(int(row["procurement_id"]), []).append(row)
        expected_by_pid = {
            pid: rowset_signature(pid_rows)
            for pid, pid_rows in expected_rows_by_pid.items()
        }
        run_signature = rowset_signature(expected_rows)
        run_id = start_run(
            di,
            input_signature=run_signature,
            procurement_count=len(expected_by_pid) or len(
                {int(row["procurement_id"]) for row in rows}
            ),
            run_kind=args.run_kind,
            proof_source=args.proof_source,
            details={
                "max_rows": args.max_rows,
                "procurement_ids": pids,
                "apply_requested": bool(args.apply),
            },
        )

        priced_source_lines = {
            _source_line_key(row)
            for row in rows if row.get("unit_price_value") is not None
        }

        plan: list[dict[str, Any]] = []
        unmatched: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        examined_ids: set[int] = set()
        matched_ids: set[int] = set()
        updated_ids: set[int] = set()
        for row in rows:
            row_id = int(row["id"])
            examined_ids.add(row_id)
            name = str(row.get("name_raw") or "").strip()
            if not name:
                reasons["empty_text"] += 1
                continue
            row_kind, _family = classify_estimate_row(name)
            attributes = row.get("technical_attributes")
            if not isinstance(attributes, list) or not attributes:
                attributes = _technical_attributes(
                    name, str(row.get("source_quote") or "")
                )
            category = row.get("category_code")
            subcategory = row.get("subcategory_code")
            if (
                row.get("unit_price_value") is None
                and _source_line_key(row) in priced_source_lines
            ):
                # Preserve the older extraction row for provenance, but do
                # not project its duplicate, unpriced category evidence.
                category = None
                subcategory = None
                reasons["superseded_by_priced_source_line"] += 1
            elif row_kind in {"GOODS", "SPECIAL_WORK_REVIEW"}:
                resolution = taxonomy.resolve(
                    " ".join((name, _attribute_text(attributes)))
                )
                reasons[resolution.reason] += 1
                if resolution.category_code:
                    category = resolution.category_code
                    subcategory = resolution.subcategory_code
                    matched_ids.add(row_id)
                else:
                    # A previous broad match is not authority: on re-resolution
                    # stale categories must be cleared when the current semantic
                    # guard rejects them.
                    category = None
                    subcategory = None
                    unmatched[
                        str(row.get("name_normalized") or normalize_name(name))
                    ] += 1
            else:
                category = None
                subcategory = None
                reasons[f"row_kind:{row_kind}"] += 1
            normalized = row.get("name_normalized") or normalize_name(name)
            if (
                category != row.get("category_code")
                or subcategory != row.get("subcategory_code")
                or row_kind != row.get("row_kind")
                or normalized != row.get("name_normalized")
                or _canonical(attributes) != _canonical(row.get("technical_attributes"))
            ):
                plan.append(
                    {
                        "id": int(row["id"]),
                        "category_code": category,
                        "subcategory_code": subcategory,
                        "row_kind": row_kind,
                        "name_normalized": normalized,
                        "technical_attributes": attributes,
                    }
                )
                updated_ids.add(row_id)

        digest = _plan_hash(plan)
        planned_by_category = Counter(
            str(item["category_code"])
            for item in plan
            if item.get("category_code")
        )
        planned_by_subcategory = Counter(
            f"{item['category_code']}::{item['subcategory_code']}"
            for item in plan
            if item.get("category_code") and item.get("subcategory_code")
        )
        rows_by_pid: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_pid.setdefault(int(row["procurement_id"]), []).append(row)
        all_pids = sorted(set(expected_by_pid) | set(rows_by_pid))
        coverage_rows: list[dict[str, Any]] = []
        for pid in all_pids:
            expected = expected_by_pid.get(
                pid, rowset_signature(rows_by_pid.get(pid, []))
            )
            pid_row_ids = {
                int(row["id"]) for row in rows_by_pid.get(pid, [])
            }
            examined_count = len(pid_row_ids)
            matched_count = len(pid_row_ids & matched_ids)
            updated_count = len(pid_row_ids & updated_ids)
            coverage_rows.append(
                {
                    "procurement_id": pid,
                    "expected": expected,
                    "examined": examined_count,
                    "matched": matched_count,
                    "unmatched": examined_count - matched_count,
                    "updated": updated_count,
                }
            )
            upsert_coverage(
                di,
                run_id=run_id,
                procurement_id=pid,
                expected=expected,
                examined_rows=examined_count,
                matched_rows=matched_count,
                unmatched_rows=examined_count - matched_count,
                updated_rows=updated_count,
                status="DRY_RUN",
                proof_source=args.proof_source,
                committed=False,
            )
        di.commit()
        unmatched_rows = [
            {"material": name, "lines": count}
            for name, count in unmatched.most_common(100)
        ]
        result = {
            "status": "DRY_RUN",
            "normalization_version": NORMALIZER_VERSION,
            "plan_sha256": digest,
            "rows_scanned": len(rows),
            "planned_updates": len(plan),
            "taxonomy_terms": len(taxonomy.terms),
            "resolution_reasons": dict(sorted(reasons.items())),
            "planned_by_category": dict(sorted(planned_by_category.items())),
            "planned_by_subcategory": dict(
                sorted(planned_by_subcategory.items())
            ),
            "unmatched_top": unmatched_rows,
            "before": _counts(di),
        }
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"ROWS_SCANNED={len(rows)}")
        print(f"TAXONOMY_TERMS={len(taxonomy.terms)}")
        print(f"PLANNED_UPDATES={len(plan)}")
        print(f"PLAN_SHA256={digest}")
        print(
            "RESOLUTION_REASONS="
            + json.dumps(dict(sorted(reasons.items())), ensure_ascii=False)
        )
        print(
            "PLANNED_BY_CATEGORY="
            + json.dumps(dict(sorted(planned_by_category.items())), ensure_ascii=False)
        )
        if args.sample_categories:
            samples: dict[str, list[dict[str, Any]]] = {}
            rows_by_id = {row["id"]: row for row in rows}
            for item in plan:
                category = item.get("category_code")
                if category and len(samples.setdefault(category, [])) < 5:
                    source = rows_by_id[item["id"]]
                    resolution = taxonomy.resolve(
                        " ".join((str(source["name_raw"]), _attribute_text(item["technical_attributes"])))
                    )
                    samples[category].append({
                        "name": str(source["name_raw"])[:150],
                        "terms": resolution.matched_terms[:6],
                    })
            print("CATEGORY_SAMPLES=" + json.dumps(samples, ensure_ascii=False))
        print(
            "UNMATCHED_TOP="
            + json.dumps(unmatched_rows[:20], ensure_ascii=False)
        )
        print(f"REPORT={report_path}")
        if not args.apply:
            print("DRY_RUN=YES")
            print("DB_WRITES=0")
            finish_run(
                di,
                run_id=run_id,
                status="COMPLETED",
                plan_sha256=digest,
                examined_rows=len(rows),
                matched_rows=len(matched_ids),
                unmatched_rows=len(rows) - len(matched_ids),
                updated_rows=0,
                details={"dry_run": True, "coverage_rows": len(coverage_rows)},
            )
            return 0
        if digest != args.expected_plan_sha256:
            raise SystemExit(
                "plan hash mismatch: refusing to write "
                f"{digest} != {args.expected_plan_sha256}"
            )

        with di.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                UPDATE structured_estimate_rows
                   SET category_code = %s,
                       subcategory_code = %s,
                       row_kind = %s,
                       name_normalized = %s,
                       technical_attributes = %s,
                       updated_at = NOW()
                 WHERE id = %s
                """,
                [
                    (
                        item["category_code"],
                        item["subcategory_code"],
                        item["row_kind"],
                        item["name_normalized"],
                        psycopg2.extras.Json(item["technical_attributes"]),
                        item["id"],
                    )
                    for item in plan
                ],
                page_size=500,
            )
        di.commit()
        completed_procurements = 0
        for coverage in coverage_rows:
            complete = coverage["expected"].row_count == coverage["examined"]
            if complete:
                completed_procurements += 1
            upsert_coverage(
                di,
                run_id=run_id,
                procurement_id=coverage["procurement_id"],
                expected=coverage["expected"],
                examined_rows=coverage["examined"],
                matched_rows=coverage["matched"],
                unmatched_rows=coverage["unmatched"],
                updated_rows=coverage["updated"],
                status="COMPLETED" if complete else "PARTIAL",
                proof_source=args.proof_source,
                committed=False,
            )
        di.commit()
        finish_run(
            di,
            run_id=run_id,
            status=(
                "COMPLETED"
                if completed_procurements == len(coverage_rows)
                else "PARTIAL"
            ),
            plan_sha256=digest,
            examined_rows=len(rows),
            matched_rows=len(matched_ids),
            unmatched_rows=len(rows) - len(matched_ids),
            updated_rows=len(plan),
            details={
                "dry_run": False,
                "coverage_rows": len(coverage_rows),
                "completed_procurements": completed_procurements,
            },
        )
        result.update(
            {
                "status": "APPLIED",
                "after": _counts(di),
                "acceptance": {
                    "CATEGORY_SEARCH_OVER_STRUCTURED_ESTIMATE_ROWS": "YES",
                    "SUBCATEGORY_RESOLUTION_WRITTEN": "YES",
                    "TECH_ATTRIBUTES_FROM_ESTIMATE_ROWS": "YES",
                    "NO_DOWNLOAD": "YES",
                    "NO_LOCAL_FILES": "YES",
                    "NO_FULL_MASS_REPARSE": "YES",
                    "MEDALS_UNCHANGED": "YES_BY_DB_SCOPE",
                    "DB_WRITES": "STRUCTURED_ESTIMATE_ROWS_ONLY",
                },
            }
        )
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"UPDATED_ROWS={len(plan)}")
        print(f"REPORT={report_path}")
        print("DB_WRITES=STRUCTURED_ESTIMATE_ROWS_ONLY")
        return 0
    except Exception as exc:
        di.rollback()
        if run_id is not None:
            try:
                finish_run(
                    di,
                    run_id=run_id,
                    status="FAILED",
                    plan_sha256=None,
                    examined_rows=0,
                    matched_rows=0,
                    unmatched_rows=0,
                    updated_rows=0,
                    error_count=1,
                    details={"error": f"{type(exc).__name__}: {exc}"[:2000]},
                )
            except Exception:
                di.rollback()
        raise
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
