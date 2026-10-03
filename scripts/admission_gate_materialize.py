#!/usr/bin/env python3
"""ADMISSION-GATE-RUNTIME-ENFORCEMENT-1 - authority materialisation + queue reconciliation.

Read-only on crm_procurements; writes only:
  * crm_procurement_scope_authority  (materialise current lifecycle+scope+admission)
  * document_intelligence.document_processing_queue.category_context
    (stamp the current admission decision on claimable rows)

Business-relevant set only (never a full 431k classification):
  A. factual ACTIVE_OPEN   : torgi + submission_open + end_date >= current_date
  B. factual AWARDED       : crm_stage = 'razygranye'
  C. current claimable rows: document_processing_queue status in (PENDING, PRE_RESEARCH_WAITING)

Run:  .venv313/bin/python scripts/admission_gate_materialize.py [--apply]
No Qwen. No downloads. No document reprocessing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, "/opt/CRM_Streamlit")

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
from src.services.pre_research_scope_gate import classify_pre_research_scope  # noqa: E402

ENV_PATH = "/opt/CRM_Streamlit/.env"
DOC_DB_NAME = "document_intelligence"
CLAIMABLE_STATUSES = ("PENDING", "PRE_RESEARCH_WAITING")
# scope_evidence is NOT NULL and CHECK'd to post_research_feature_count='0'.
SCOPE_EVIDENCE_JSON = json.dumps({"post_research_feature_count": "0"})


def load_env(path: str = ENV_PATH) -> dict:
    env: dict = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _params(env: dict, dbname: str) -> dict:
    return {
        "host": env.get("CRM_DB_HOST", "127.0.0.1"),
        "port": int(env.get("CRM_DB_PORT", "5432")),
        "dbname": dbname,
        "user": env.get("CRM_DB_USER"),
        "password": env.get("CRM_DB_PASSWORD"),
    }


def business_relevant_ids(crm_cur, doc_cur) -> list:
    crm_cur.execute(
        """
        SELECT id FROM crm_procurements
         WHERE crm_stage = 'torgi' AND award_status = 'submission_open'
           AND end_date >= CURRENT_DATE
        UNION
        SELECT id FROM crm_procurements WHERE crm_stage = 'razygranye'
        """
    )
    ids = {int(r["id"]) for r in crm_cur.fetchall()}
    doc_cur.execute(
        "SELECT DISTINCT procurement_id FROM document_processing_queue "
        "WHERE status IN %s",
        (CLAIMABLE_STATUSES,),
    )
    ids |= {
        int(r["procurement_id"])
        for r in doc_cur.fetchall()
        if r["procurement_id"] is not None
    }
    return sorted(ids)


def load_authority(crm_cur, ids) -> dict:
    out = {}
    for i in range(0, len(ids), 5000):
        crm_cur.execute(
            """SELECT procurement_id, source_lifecycle, procurement_scope_type,
                      scope_confidence, scope_method, scope_version,
                      admission_state, admission_reason, admission_policy_version
                 FROM crm_procurement_scope_authority
                WHERE procurement_id = ANY(%s)""",
            (ids[i : i + 5000],),
        )
        for r in crm_cur.fetchall():
            out[int(r["procurement_id"])] = dict(r)
    return out


def build_rows(crm_cur, ids, existing):
    crm_cur.execute(
        """SELECT id, source_table, crm_stage, award_status, end_date, auction_name, okpd_code
             FROM crm_procurements WHERE id = ANY(%s)""",
        (ids,),
    )
    rows = []
    for p in crm_cur.fetchall():
        pid = int(p["id"])
        lifecycle = normalize_source_lifecycle_event(
            source_table=p.get("source_table") or "",
            crm_stage=p.get("crm_stage") or "",
            award_status=p.get("award_status") or "",
            end_date=p.get("end_date"),
        ).value
        ex = existing.get(pid)
        if ex and ex.get("procurement_scope_type"):
            scope = ex["procurement_scope_type"]
            conf = ex.get("scope_confidence")
            method = ex.get("scope_method") or "PRE_RESEARCH_SCOPE_GATE"
            ver = ex.get("scope_version") or "1.1"
        else:
            scope = classify_pre_research_scope(
                p.get("auction_name"), p.get("okpd_code")
            )["procurement_scope_type"]
            conf = 0.9
            method = "PRE_RESEARCH_SCOPE_GATE"
            ver = "1.1"
        state, reason = decide_admission(lifecycle, scope)
        rows.append(
            (
                pid,
                lifecycle,
                scope,
                conf,
                method,
                ver,
                SCOPE_EVIDENCE_JSON,
                state,
                reason,
                ADMISSION_POLICY_VERSION,
            )
        )
    return rows


def upsert_authority(crm_cur, rows):
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
            source_lifecycle        = EXCLUDED.source_lifecycle,
            procurement_scope_type  = EXCLUDED.procurement_scope_type,
            scope_confidence        = EXCLUDED.scope_confidence,
            scope_method            = EXCLUDED.scope_method,
            scope_version           = EXCLUDED.scope_version,
            scope_evidence          = COALESCE(crm_procurement_scope_authority.scope_evidence, EXCLUDED.scope_evidence),
            admission_state         = EXCLUDED.admission_state,
            admission_reason        = EXCLUDED.admission_reason,
            admission_policy_version= EXCLUDED.admission_policy_version,
            admission_evaluated_at  = EXCLUDED.admission_evaluated_at,
            updated_at              = EXCLUDED.updated_at
        """,
        rows,
        template="(%s,%s,%s,%s,%s,%s,%s::jsonb, now(), %s,%s,%s, now(), now())",
        page_size=1000,
    )


def reconcile_queue(doc_cur, crm_cur, authority, apply: bool):
    doc_cur.execute(
        "SELECT id, procurement_id FROM document_processing_queue WHERE status IN %s",
        (CLAIMABLE_STATUSES,),
    )
    claimable = doc_cur.fetchall()
    missing_pids = [int(r["procurement_id"]) for r in claimable
                    if int(r["procurement_id"]) not in authority]
    if missing_pids:
        authority.update(load_authority(crm_cur, sorted(set(missing_pids))))

    changes = Counter()
    for r in claimable:
        pid = int(r["procurement_id"])
        fields = context_admission_fields(authority.get(pid))
        old = authority.get(pid) or {}
        changes[(fields["admission_state"], pid in authority)] += 1
        if apply:
            doc_cur.execute(
                "UPDATE document_processing_queue "
                "SET category_context = COALESCE(category_context, '{}'::jsonb) || %s::jsonb "
                "WHERE id = %s",
                (json.dumps(fields, default=str), r["id"]),
            )
    return len(claimable), changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    args = ap.parse_args()

    env = load_env()
    crm = psycopg2.connect(**_params(env, env.get("CRM_DB_DATABASE", "crm")))
    doc = psycopg2.connect(**_params(env, DOC_DB_NAME))
    crm.autocommit = False
    doc.autocommit = False
    try:
        with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as ccur, \
             doc.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
            ids = business_relevant_ids(ccur, dcur)
            existing = load_authority(ccur, ids)
            rows = build_rows(ccur, ids, existing)
            states = Counter(r[7] for r in rows)
            print(f"business_relevant_ids={len(ids)} states={dict(states)}")
            if args.apply:
                upsert_authority(ccur, rows)
            materialised = {
                r[0]: {
                    **existing.get(r[0], {}),
                    "admission_state": r[7],
                    "admission_reason": r[8],
                    "admission_policy_version": r[9],
                    "source_lifecycle": r[1],
                    "procurement_scope_type": r[2],
                }
                for r in rows
            }
            n_claim, changes = reconcile_queue(
                dcur, ccur, {**existing, **materialised}, apply=args.apply
            )
            print(f"claimable_rows={n_claim} queue_admission={ {f'{k[0]}:authority={k[1]}': v for k, v in changes.items()} }")
        if args.apply:
            crm.commit()
            doc.commit()
            print("COMMITTED")
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
