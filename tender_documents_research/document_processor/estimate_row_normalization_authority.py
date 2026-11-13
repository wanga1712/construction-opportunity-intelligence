"""Durable run, coverage and rowset-fingerprint authority for row taxonomy."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from psycopg2.extras import Json

NORMALIZER_VERSION = "estimate_row_taxonomy_resolver_v1"


@dataclass(frozen=True)
class RowsetSignature:
    row_count: int
    max_row_id: int | None
    sha256: str


def rowset_signature(rows: Iterable[Mapping[str, Any]]) -> RowsetSignature:
    ordered = sorted(rows, key=lambda row: int(row.get("id") or 0))
    payload = [
        {
            "id": int(row.get("id") or 0),
            "procurement_id": int(row.get("procurement_id") or 0),
            "source_document_id": row.get("source_document_id"),
            "row_ref": row.get("row_ref"),
            "name_raw": row.get("name_raw"),
        }
        for row in ordered
    ]
    digest = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, default=str
        ).encode("utf-8")
    ).hexdigest()
    return RowsetSignature(
        row_count=len(payload),
        max_row_id=payload[-1]["id"] if payload else None,
        sha256=digest,
    )


def normalization_state(
    *,
    current: RowsetSignature,
    coverage: Mapping[str, Any] | None,
    version: str = NORMALIZER_VERSION,
) -> str:
    """Return completion state without using category_code as proof."""
    if not coverage:
        return "NOT_PROVEN_NORMALIZED"
    if str(coverage.get("normalizer_version") or "") != version:
        return "NOT_PROVEN_FOR_VERSION"
    if (
        int(coverage.get("input_row_count") or 0) != current.row_count
        or coverage.get("input_max_row_id") != current.max_row_id
        or str(coverage.get("input_rows_sha256") or "") != current.sha256
    ):
        return "STALE"
    state = str(coverage.get("status") or "").upper()
    if state == "FAILED":
        return "FAILED"
    if state == "STALE":
        return "STALE"
    if state == "DRY_RUN":
        return "DRY_RUN"
    if state == "NOT_ATTEMPTED":
        return "NOT_ATTEMPTED"
    if bool(coverage.get("coverage_complete")) and state == "COMPLETED":
        return "COMPLETED"
    return "PARTIAL"


def start_run(
    conn: Any,
    *,
    input_signature: RowsetSignature,
    procurement_count: int,
    run_kind: str,
    proof_source: str,
    details: Mapping[str, Any] | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO estimate_row_normalization_runs
                (normalizer_version, status, run_kind, proof_source,
                 procurement_count, row_count_expected, input_row_count,
                 input_max_row_id, input_rows_sha256, details)
            VALUES (%s,'RUNNING',%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                NORMALIZER_VERSION,
                run_kind,
                proof_source,
                procurement_count,
                input_signature.row_count,
                input_signature.row_count,
                input_signature.max_row_id,
                input_signature.sha256,
                Json(dict(details or {})),
            ),
        )
        run_id = int(cur.fetchone()[0])
    conn.commit()
    return run_id


def upsert_coverage(
    conn: Any,
    *,
    run_id: int,
    procurement_id: int,
    expected: RowsetSignature,
    examined_rows: int,
    matched_rows: int,
    unmatched_rows: int,
    updated_rows: int,
    status: str,
    proof_source: str,
    committed: bool = True,
) -> None:
    complete = expected.row_count == int(examined_rows)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO estimate_row_normalization_procurements
                (run_id, procurement_id, normalizer_version,
                 rows_expected, rows_examined, rows_matched, rows_unmatched,
                 rows_updated, coverage_complete, status,
                 input_row_count, input_max_row_id, input_rows_sha256,
                 proof_source, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (run_id, procurement_id) DO UPDATE SET
                rows_examined = EXCLUDED.rows_examined,
                rows_matched = EXCLUDED.rows_matched,
                rows_unmatched = EXCLUDED.rows_unmatched,
                rows_updated = EXCLUDED.rows_updated,
                coverage_complete = EXCLUDED.coverage_complete,
                status = EXCLUDED.status,
                input_row_count = EXCLUDED.input_row_count,
                input_max_row_id = EXCLUDED.input_max_row_id,
                input_rows_sha256 = EXCLUDED.input_rows_sha256,
                proof_source = EXCLUDED.proof_source,
                updated_at = NOW()
            """,
            (
                run_id, procurement_id, NORMALIZER_VERSION,
                expected.row_count, examined_rows, matched_rows, unmatched_rows,
                updated_rows, complete, status,
                expected.row_count, expected.max_row_id, expected.sha256,
                proof_source,
            ),
        )
    if committed:
        conn.commit()


def finish_run(
    conn: Any,
    *,
    run_id: int,
    status: str,
    plan_sha256: str | None,
    examined_rows: int,
    matched_rows: int,
    unmatched_rows: int,
    updated_rows: int,
    error_count: int = 0,
    details: Mapping[str, Any] | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE estimate_row_normalization_runs
               SET completed_at=NOW(), status=%s, plan_sha256=%s,
                   row_count_examined=%s, matched_rows=%s,
                   unmatched_rows=%s, updated_rows=%s, error_count=%s,
                   details=details || %s
             WHERE id=%s
            """,
            (
                status, plan_sha256, examined_rows, matched_rows,
                unmatched_rows, updated_rows, error_count,
                Json(dict(details or {})), run_id,
            ),
        )
    conn.commit()


def load_current_signature(conn: Any, procurement_id: int) -> RowsetSignature:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, procurement_id, source_document_id, row_ref, name_raw
              FROM structured_estimate_rows
             WHERE procurement_id=%s
             ORDER BY id
            """,
            (procurement_id,),
        )
        rows = [
            {
                "id": row[0], "procurement_id": row[1],
                "source_document_id": row[2], "row_ref": row[3],
                "name_raw": row[4],
            }
            for row in cur.fetchall()
        ]
    return rowset_signature(rows)


def load_normalization_state(
    conn: Any,
    procurement_id: int,
    *,
    version: str = NORMALIZER_VERSION,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT normalizer_version, coverage_complete, status,
                   input_row_count, input_max_row_id, input_rows_sha256
              FROM estimate_row_normalization_procurements
             WHERE procurement_id=%s
             ORDER BY updated_at DESC, run_id DESC
             LIMIT 1
            """,
            (procurement_id,),
        )
        row = cur.fetchone()
    coverage = None
    if row:
        coverage = {
            "normalizer_version": row[0],
            "coverage_complete": row[1],
            "status": row[2],
            "input_row_count": row[3],
            "input_max_row_id": row[4],
            "input_rows_sha256": row[5],
        }
    return normalization_state(
        current=load_current_signature(conn, procurement_id),
        coverage=coverage,
        version=version,
    )
