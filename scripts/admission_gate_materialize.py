#!/usr/bin/env python3
"""Materialise business research admission and queue provenance.

Dry-run is the default. No CRM or document-intelligence write occurs unless the
operator explicitly passes ``--apply``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from src.services.commercial_routing_v3.business_research_admission import (  # noqa: E402
    ADMISSION_POLICY_VERSION,
    context_admission_fields,
    decide_admission,
)
from src.services.commercial_routing_v3.source_lifecycle import (  # noqa: E402
    normalize_source_lifecycle_event,
)
from src.services.pre_research_scope_gate import (  # noqa: E402
    classify_pre_research_scope,
)

DEFAULT_ENV_PATH = ROOT / ".env"
DOC_DB_NAME = "document_intelligence"
CLAIMABLE_STATUSES = ("PENDING", "PRE_RESEARCH_WAITING")
SCOPE_EVIDENCE_JSON = json.dumps({"post_research_feature_count": "0"})


@dataclass
class MaterializationPlan:
    inspected: int = 0
    authority_rows: List[tuple] = field(default_factory=list)
    queue_updates: List[Dict[str, Any]] = field(default_factory=list)
    admission_changes: Counter = field(default_factory=Counter)
    crm_operations: Counter = field(default_factory=Counter)
    queue_change_states: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "inspected": self.inspected,
            "planned_admission_changes": {
                "count": sum(self.admission_changes.values()),
                "by_state": dict(self.admission_changes),
            },
            "planned_crm_writes": {
                "count": len(self.authority_rows),
                "by_operation": dict(self.crm_operations),
            },
            "planned_queue_changes": {
                "count": len(self.queue_updates),
                "by_state": dict(self.queue_change_states),
            },
            "skipped": dict(self.skipped),
            "errors": list(self.errors),
        }


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict:
    env: dict = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _params(env: dict, dbname: str) -> dict:
    return {
        "host": env.get("CRM_DB_HOST", "127.0.0.1"),
        "port": int(env.get("CRM_DB_PORT", "5432")),
        "dbname": dbname,
        "user": env.get("CRM_DB_USER"),
        "password": env.get("CRM_DB_PASSWORD"),
    }


def business_relevant_ids(crm_cur, doc_cur) -> List[int]:
    crm_cur.execute(
        "SELECT id FROM crm_procurements "
        "WHERE crm_stage IN ('torgi', 'commission', 'razygranye')"
    )
    ids = {int(row["id"]) for row in crm_cur.fetchall()}
    crm_cur.execute("SELECT procurement_id FROM crm_procurement_scope_authority")
    ids.update(
        int(row["procurement_id"])
        for row in crm_cur.fetchall()
        if row["procurement_id"] is not None
    )
    doc_cur.execute(
        "SELECT DISTINCT procurement_id FROM document_processing_queue "
        "WHERE status IN %s",
        (CLAIMABLE_STATUSES,),
    )
    ids.update(
        int(row["procurement_id"])
        for row in doc_cur.fetchall()
        if row["procurement_id"] is not None
    )
    return sorted(ids)


def load_authority(crm_cur, ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for start in range(0, len(ids), 5000):
        crm_cur.execute(
            """
            SELECT procurement_id, source_lifecycle, procurement_scope_type,
                   scope_confidence, scope_method, scope_version,
                   admission_state, admission_reason, admission_policy_version,
                   admission_evaluated_at
              FROM crm_procurement_scope_authority
             WHERE procurement_id = ANY(%s)
            """,
            (list(ids[start : start + 5000]),),
        )
        for row in crm_cur.fetchall() or []:
            record = dict(row)
            out[int(record["procurement_id"])] = record
    return out


def load_procurements(crm_cur, ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    rows: Dict[int, Dict[str, Any]] = {}
    for start in range(0, len(ids), 5000):
        crm_cur.execute(
            """
            SELECT id, source_table, crm_stage, award_status, end_date,
                   auction_name, okpd_code
              FROM crm_procurements
             WHERE id = ANY(%s)
            """,
            (list(ids[start : start + 5000]),),
        )
        for row in crm_cur.fetchall() or []:
            record = dict(row)
            rows[int(record["id"])] = record
    return rows


def load_claimable_queue(doc_cur) -> List[Dict[str, Any]]:
    doc_cur.execute(
        "SELECT id, procurement_id, category_context "
        "FROM document_processing_queue WHERE status IN %s",
        (CLAIMABLE_STATUSES,),
    )
    return [dict(row) for row in doc_cur.fetchall() or []]


def _authority_tuple(
    procurement_id: int,
    lifecycle: str,
    scope: str,
    confidence: Any,
    method: str,
    version: str,
    state: str,
    reason: str,
) -> tuple:
    return (
        procurement_id,
        lifecycle,
        scope,
        confidence,
        method,
        version,
        SCOPE_EVIDENCE_JSON,
        state,
        reason,
        ADMISSION_POLICY_VERSION,
    )


def _authority_record(
    existing: Optional[Dict[str, Any]],
    row: tuple,
    evaluated_at: str,
) -> Dict[str, Any]:
    return {
        **(existing or {}),
        "procurement_id": row[0],
        "source_lifecycle": row[1],
        "procurement_scope_type": row[2],
        "scope_confidence": row[3],
        "scope_method": row[4],
        "scope_version": row[5],
        "admission_state": row[7],
        "admission_reason": row[8],
        "admission_policy_version": row[9],
        "admission_evaluated_at": evaluated_at,
    }


def _admission_changed(existing: Optional[Dict[str, Any]], row: tuple) -> bool:
    if existing is None:
        return True
    return any(
        (
            existing.get("source_lifecycle") != row[1],
            existing.get("procurement_scope_type") != row[2],
            existing.get("admission_state") != row[7],
            existing.get("admission_reason") != row[8],
            existing.get("admission_policy_version") != row[9],
        )
    )


def _context_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _context_changed(current: Dict[str, Any], desired: Dict[str, Any]) -> bool:
    return any(current.get(key) != value for key, value in desired.items())


def plan_from_records(
    ids: Iterable[int],
    procurements: Dict[int, Dict[str, Any]],
    existing: Dict[int, Dict[str, Any]],
    queue_rows: Sequence[Dict[str, Any]],
    *,
    authority_only: bool = False,
    evaluated_at: Optional[str] = None,
) -> MaterializationPlan:
    """Build a deterministic, side-effect-free materialisation plan."""
    id_list = sorted({int(value) for value in ids})
    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()
    plan = MaterializationPlan(inspected=len(id_list))
    authority: Dict[int, Dict[str, Any]] = dict(existing)

    for procurement_id in id_list:
        procurement = procurements.get(procurement_id)
        if procurement is None:
            plan.skipped["missing_crm_procurement"] += 1
            continue
        lifecycle = normalize_source_lifecycle_event(
            source_table=procurement.get("source_table") or "",
            crm_stage=procurement.get("crm_stage") or "",
            award_status=procurement.get("award_status") or "",
            end_date=procurement.get("end_date"),
        ).value
        current = existing.get(procurement_id)
        if current and current.get("procurement_scope_type"):
            scope = current["procurement_scope_type"]
            confidence = current.get("scope_confidence")
            method = current.get("scope_method") or "PRE_RESEARCH_SCOPE_GATE"
            version = current.get("scope_version") or "1.1"
        else:
            scope_result = classify_pre_research_scope(
                procurement.get("auction_name"),
                procurement.get("okpd_code"),
            )
            scope = scope_result["procurement_scope_type"]
            confidence = scope_result.get("scope_confidence", 0.9)
            method = scope_result.get("scope_method") or "PRE_RESEARCH_SCOPE_GATE"
            version = scope_result.get("scope_version") or "1.1"
        state, reason = decide_admission(lifecycle, scope)
        row = _authority_tuple(
            procurement_id,
            lifecycle,
            scope,
            confidence,
            method,
            version,
            state,
            reason,
        )
        plan.authority_rows.append(row)
        plan.crm_operations["insert" if current is None else "update"] += 1
        if _admission_changed(current, row):
            plan.admission_changes[state] += 1
        else:
            plan.skipped["unchanged_admission"] += 1
        authority[procurement_id] = _authority_record(current, row, timestamp)

    if authority_only:
        plan.skipped["queue_reconciliation_skipped"] += 1
        return plan

    for queue_row in queue_rows:
        queue_id = int(queue_row["id"])
        procurement_id = queue_row.get("procurement_id")
        pid = int(procurement_id) if procurement_id is not None else None
        desired = context_admission_fields(authority.get(pid) if pid else None)
        current_context = _context_dict(queue_row.get("category_context"))
        if not _context_changed(current_context, desired):
            plan.skipped["unchanged_queue_context"] += 1
            continue
        plan.queue_updates.append(
            {
                "id": queue_id,
                "procurement_id": pid,
                "fields": desired,
                "from_state": current_context.get("admission_state"),
                "to_state": desired["admission_state"],
            }
        )
        plan.queue_change_states[desired["admission_state"]] += 1
    return plan


def build_plan(crm_cur, doc_cur, *, authority_only: bool = False) -> MaterializationPlan:
    ids = business_relevant_ids(crm_cur, doc_cur)
    existing = load_authority(crm_cur, ids)
    procurements = load_procurements(crm_cur, ids)
    queue_rows = [] if authority_only else load_claimable_queue(doc_cur)
    return plan_from_records(
        ids,
        procurements,
        existing,
        queue_rows,
        authority_only=authority_only,
    )


def upsert_authority(crm_cur, rows: Sequence[tuple]) -> None:
    if not rows:
        return
    psycopg2.extras.execute_values(
        crm_cur,
        """
        INSERT INTO crm_procurement_scope_authority
            (procurement_id, source_lifecycle, procurement_scope_type,
             scope_confidence, scope_method, scope_version, scope_evidence,
             scope_evaluated_at,
             admission_state, admission_reason, admission_policy_version,
             admission_evaluated_at, updated_at)
        VALUES %s
        ON CONFLICT (procurement_id) DO UPDATE SET
            source_lifecycle = EXCLUDED.source_lifecycle,
            procurement_scope_type = EXCLUDED.procurement_scope_type,
            scope_confidence = EXCLUDED.scope_confidence,
            scope_method = EXCLUDED.scope_method,
            scope_version = EXCLUDED.scope_version,
            admission_state = EXCLUDED.admission_state,
            admission_reason = EXCLUDED.admission_reason,
            admission_policy_version = EXCLUDED.admission_policy_version,
            admission_evaluated_at = EXCLUDED.admission_evaluated_at,
            updated_at = EXCLUDED.updated_at
        """,
        rows,
        template="(%s,%s,%s,%s,%s,%s,%s::jsonb, now(), %s,%s,%s, now(), now())",
        page_size=1000,
    )


def apply_plan(crm_cur, doc_cur, plan: MaterializationPlan) -> Dict[str, int]:
    """Apply an already-built plan. Callers must explicitly request --apply."""
    upsert_authority(crm_cur, plan.authority_rows)
    for change in plan.queue_updates:
        doc_cur.execute(
            "UPDATE document_processing_queue "
            "SET category_context = COALESCE(category_context, '{}'::jsonb) || %s::jsonb "
            "WHERE id = %s",
            (json.dumps(change["fields"], default=str), change["id"]),
        )
    return {
        "authority_rows": len(plan.authority_rows),
        "queue_rows": len(plan.queue_updates),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the reviewed plan; absent means dry-run",
    )
    parser.add_argument(
        "--authority-only",
        action="store_true",
        help="plan/materialise CRM authority only; never touch document queue",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(os.getenv("CRM_ENV_PATH", DEFAULT_ENV_PATH)),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    env = load_env(args.env_file)
    crm = psycopg2.connect(
        **_params(env, env.get("CRM_DB_DATABASE", "crm"))
    )
    doc = psycopg2.connect(**_params(env, DOC_DB_NAME))
    if not args.apply:
        crm.set_session(readonly=True)
        doc.set_session(readonly=True)
    try:
        with crm.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as crm_cur, doc.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as doc_cur:
            plan = build_plan(
                crm_cur,
                doc_cur,
                authority_only=args.authority_only,
            )
            print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
            if args.apply:
                applied = apply_plan(crm_cur, doc_cur, plan)
                crm.commit()
                doc.commit()
                print(json.dumps({"applied": applied}, ensure_ascii=False))
            else:
                crm.rollback()
                doc.rollback()
                print("DRY_RUN")
    finally:
        crm.close()
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
