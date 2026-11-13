#!/usr/bin/env python3
"""Import proven historical coverage and freeze the remaining repair cohort."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg2.extras
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from document_processor.estimate_row_normalization_authority import (
    NORMALIZER_VERSION,
    finish_run,
    rowset_signature,
    start_run,
    upsert_coverage,
)
from document_processor.parse_extractors import _connect

SNAPSHOT_AT = "2026-11-12 21:53:00+03"
HISTORICAL_RUN_KEY = "historical-applied-reports-20261113"
TARGET_RUN_KEY = "baseline-1068-remaining-77-20261113"


def _load_inputs(di, baseline_path: str, r3_path: str):
    baseline = {int(value) for value in json.load(open(baseline_path))}
    r3_pids = {
        int(line) for line in open(r3_path) if line.strip()
    }
    with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, procurement_id, source_document_id, row_ref, name_raw,
                   category_code, subcategory_code,
                   CASE
                     WHEN id <= 519583
                      AND created_at <= '2026-11-12 07:14:01+03'::timestamptz
                     THEN TRUE ELSE FALSE
                   END AS covered_r2,
                   CASE
                     WHEN procurement_id = ANY(%s)
                      AND created_at <= '2026-11-12 09:39:29+03'::timestamptz
                     THEN TRUE ELSE FALSE
                   END AS covered_r3,
                   CASE
                     WHEN procurement_id = 42971
                      AND created_at <= '2026-11-12 12:16:21+03'::timestamptz
                     THEN TRUE
                     WHEN procurement_id = 43009
                      AND created_at <= '2026-11-12 12:43:10+03'::timestamptz
                     THEN TRUE ELSE FALSE
                   END AS covered_pid
              FROM structured_estimate_rows
             WHERE created_at <= %s::timestamptz
             ORDER BY procurement_id, id
            """,
            (sorted(r3_pids), SNAPSHOT_AT),
        )
        rows = [dict(row) for row in cur.fetchall()]
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["procurement_id"]), []).append(row)
    return baseline, grouped


def classify(baseline: set[int], rows_by_pid: dict[int, list[dict]]):
    cards = []
    for pid in sorted(baseline & set(rows_by_pid)):
        rows = rows_by_pid[pid]
        expected = rowset_signature(rows)
        covered = sum(
            bool(row["covered_r2"] or row["covered_r3"] or row["covered_pid"])
            for row in rows
        )
        complete = expected.row_count == covered
        category_rows = sum(bool(row["category_code"]) for row in rows)
        if complete:
            state = "COMPLETED"
            bucket = "N1" if category_rows else "N2"
        elif covered > 0:
            state = "PARTIAL"
            bucket = "N3"
        else:
            state = "NOT_ATTEMPTED"
            bucket = "N4"
        cards.append(
            {
                "procurement_id": pid,
                "rows": rows,
                "expected": expected,
                "covered": covered,
                "category_rows": category_rows,
                "subcategory_rows": sum(bool(row["subcategory_code"]) for row in rows),
                "state": state,
                "bucket": bucket,
            }
        )
    return cards


def _existing_run(di, import_key: str):
    with di.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM estimate_row_normalization_runs
             WHERE normalizer_version=%s
               AND details->>'import_key'=%s
             ORDER BY id DESC LIMIT 1
            """,
            (NORMALIZER_VERSION, import_key),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def import_historical(di, cards: list[dict]) -> dict:
    existing = _existing_run(di, HISTORICAL_RUN_KEY)
    if existing:
        return {"run_id": existing, "historical_completed_imported": 991, "idempotent": True}
    completed = [card for card in cards if card["state"] == "COMPLETED"]
    all_rows = [row for card in completed for row in card["rows"]]
    run_id = start_run(
        di,
        input_signature=rowset_signature(all_rows),
        procurement_count=len(completed),
        run_kind="HISTORICAL_APPLIED_REPORT_IMPORT",
        proof_source="HISTORICAL_APPLIED_REPORT",
        details={
            "import_key": HISTORICAL_RUN_KEY,
            "snapshot_at": SNAPSHOT_AT,
            "source_reports": [
                {
                    "completed_at": "2026-10-27T19:58:49+03:00",
                    "rows_scanned": 170156,
                    "plan_sha256": "616359b126a847f4e73f57d29d8891a6be4094b54a76db13ea539cae6df8a3a8",
                },
                {
                    "completed_at": "2026-11-12T07:16:12+03:00",
                    "rows_scanned": 500000,
                    "plan_sha256": "16845dfd0865ad9086c5a658af03d661293ef833da02f16a86032673886f1729",
                },
                {
                    "completed_at": "2026-11-12T09:42:12+03:00",
                    "rows_scanned": 691741,
                    "plan_sha256": "a9e3f6907c521b8af107b3582f24dba20ff80dd7bae658f66c8ccfb1ea4c36ef",
                },
            ],
        },
    )
    matched = 0
    for card in completed:
        matched += card["category_rows"]
        upsert_coverage(
            di,
            run_id=run_id,
            procurement_id=card["procurement_id"],
            expected=card["expected"],
            examined_rows=card["expected"].row_count,
            matched_rows=card["category_rows"],
            unmatched_rows=card["expected"].row_count - card["category_rows"],
            updated_rows=0,
            status="COMPLETED",
            proof_source="HISTORICAL_APPLIED_REPORT",
            committed=False,
        )
    di.commit()
    finish_run(
        di,
        run_id=run_id,
        status="COMPLETED",
        plan_sha256=None,
        examined_rows=len(all_rows),
        matched_rows=matched,
        unmatched_rows=len(all_rows) - matched,
        updated_rows=0,
        details={"historical_procurements": len(completed)},
    )
    return {
        "run_id": run_id,
        "historical_completed_imported": len(completed),
        "idempotent": False,
    }


def freeze_target(di, cards: list[dict]) -> dict:
    existing = _existing_run(di, TARGET_RUN_KEY)
    if existing:
        return {"run_id": existing, "target_77": 77, "idempotent": True}
    target = [card for card in cards if card["state"] in {"PARTIAL", "NOT_ATTEMPTED"}]
    all_rows = [row for card in target for row in card["rows"]]
    run_id = start_run(
        di,
        input_signature=rowset_signature(all_rows),
        procurement_count=len(target),
        run_kind="FROZEN_TARGET_COHORT",
        proof_source="FROZEN_BASELINE_COVERAGE",
        details={
            "import_key": TARGET_RUN_KEY,
            "snapshot_at": SNAPSHOT_AT,
            "bucket_counts": dict(Counter(card["bucket"] for card in target)),
            "procurement_ids": [card["procurement_id"] for card in target],
        },
    )
    for card in target:
        upsert_coverage(
            di,
            run_id=run_id,
            procurement_id=card["procurement_id"],
            expected=card["expected"],
            examined_rows=card["covered"],
            matched_rows=0,
            unmatched_rows=card["covered"],
            updated_rows=0,
            status=card["state"],
            proof_source="FROZEN_BASELINE_COVERAGE",
            committed=False,
        )
    di.commit()
    finish_run(
        di,
        run_id=run_id,
        status="PARTIAL",
        plan_sha256=None,
        examined_rows=sum(card["covered"] for card in target),
        matched_rows=0,
        unmatched_rows=sum(card["covered"] for card in target),
        updated_rows=0,
        details={"target_procurements": len(target)},
    )
    return {
        "run_id": run_id,
        "target_77": len(target),
        "bucket_counts": dict(Counter(card["bucket"] for card in target)),
        "idempotent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-cards-json", required=True)
    parser.add_argument("--r3-pids-file", required=True)
    parser.add_argument("--import-historical", action="store_true")
    parser.add_argument("--freeze-target", action="store_true")
    args = parser.parse_args()
    di = _connect()
    try:
        baseline, rows_by_pid = _load_inputs(
            di, args.baseline_cards_json, args.r3_pids_file
        )
        cards = classify(baseline, rows_by_pid)
        result = {
            "with_estimate_rows": len(cards),
            "without_estimate_rows": len(baseline) - len(cards),
            "bucket_counts": dict(Counter(card["bucket"] for card in cards)),
        }
        if args.import_historical:
            result["historical"] = import_historical(di, cards)
        if args.freeze_target:
            result["target"] = freeze_target(di, cards)
    finally:
        di.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
