#!/usr/bin/env python3
"""Phase 1d: robust source counts + awarded/open mismatches via raw SQL."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from src.bootstrap import setup_source_path

setup_source_path()

from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.db_bootstrap import connect_databases
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
import psycopg2
from psycopg2.extras import RealDictCursor


def crm_q(sql, params=None):
    conn = psycopg2.connect(**require_crm_db_connect_kwargs())
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def src_q(sql, params=None):
    # tender_monitor on S7 via same host pattern used by runtime
    kw = dict(require_crm_db_connect_kwargs())
    kw["dbname"] = "tender_monitor"
    # Prefer S7 host if configured in env through existing tender connection
    _, tender, _, _ = connect_databases()
    # Use tender's underlying connection manager if possible
    rows = tender.execute_query(sql, params)
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(r)
        else:
            # convert sequence to list
            out.append(list(r))
    return out


def main() -> int:
    where = (
        "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND "
        + actionable_submission_sql("cp")
    )
    total = crm_q(f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {where}")[0]["c"]
    created_today = crm_q(
        f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {where} AND date(crm_created_at)=CURRENT_DATE"
    )[0]["c"]
    print("FINAL_UI_TORGI", total)
    print("CREATED_TODAY", created_today)
    print("STOCK_BEFORE_TODAY", total - created_today)

    # Source counts via tender connection with positional results
    tables = [
        "reestr_contract_44_fz",
        "reestr_contract_44_fz_commission_work",
        "reestr_contract_44_fz_awarded",
        "reestr_contract_223_fz",
        "reestr_contract_223_fz_commission_work",
        "reestr_contract_223_fz_awarded",
        "reestr_contract_615_pp",
        "reestr_contract_615_pp_commission_work",
    ]
    print("\nSOURCE_COUNTS")
    _, tender, _, _ = connect_databases()
    for t in tables:
        try:
            rows = tender.execute_query(f"SELECT COUNT(*) FROM {t}")
            c = rows[0][0] if not isinstance(rows[0], dict) else list(rows[0].values())[0]
            print(f"{t}={c}")
        except Exception as exc:
            print(f"{t}=ERR:{type(exc).__name__}:{exc}")

    # Column discovery for awarded
    print("\nAWARDED_COLUMNS")
    for t in ("reestr_contract_44_fz_awarded", "reestr_contract_223_fz_awarded"):
        rows = tender.execute_query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (t,),
        )
        cols = [r[0] if not isinstance(r, dict) else r.get("column_name") or list(r.values())[0] for r in rows]
        print(t, cols[:40])

    # Open CRM actionable CNs in source awarded using placer/reg fields after discovery
    print("\nCROSS_MATCH")
    for open_table, awarded_table, num_candidates in (
        (
            "reestr_contract_44_fz",
            "reestr_contract_44_fz_awarded",
            ("purchaseNumber", "purchase_number", "notification_number", "reg_number", "reestr_number"),
        ),
        (
            "reestr_contract_223_fz",
            "reestr_contract_223_fz_awarded",
            ("registrationNumber", "registration_number", "reg_number", "notice_number"),
        ),
    ):
        rows = tender.execute_query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
            (awarded_table,),
        )
        cols = {r[0] if not isinstance(r, dict) else (r.get("column_name") or list(r.values())[0]) for r in rows}
        num_col = next((c for c in num_candidates if c in cols), None)
        # also case-insensitive
        if not num_col:
            lower = {c.lower(): c for c in cols}
            for c in num_candidates:
                if c.lower() in lower:
                    num_col = lower[c.lower()]
                    break
        print(awarded_table, "NUM_COL", num_col)
        if not num_col:
            continue
        open_cns = [
            r["cn"]
            for r in crm_q(
                f"""
                SELECT btrim(contract_number) AS cn
                FROM crm_procurements cp
                WHERE {where} AND source_table=%s
                  AND contract_number IS NOT NULL AND btrim(contract_number)<>''
                """,
                (open_table,),
            )
        ]
        print(open_table, "OPEN_CN", len(open_cns))
        hits = 0
        samples = []
        for i in range(0, len(open_cns), 400):
            chunk = open_cns[i : i + 400]
            found = tender.execute_query(
                f"SELECT DISTINCT {num_col}::text FROM {awarded_table} WHERE {num_col}::text = ANY(%s)",
                (chunk,),
            )
            for row in found or []:
                hits += 1
                val = row[0] if not isinstance(row, dict) else list(row.values())[0]
                if len(samples) < 5:
                    samples.append(val)
        print("OPEN_IN_SOURCE_AWARDED", hits, "SAMPLES", samples)

    # CRM 615 presence
    print("\nCRM_615")
    for r in crm_q(
        """
        SELECT source_table, crm_stage, award_status, COUNT(*) AS c
        FROM crm_procurements
        WHERE source_table ILIKE '%%615%%'
        GROUP BY 1,2,3 ORDER BY c DESC
        """
    ):
        print(dict(r))

    # Sync writer: how many submission_open have source_awarded_* set
    print("\nOPEN_WITH_SOURCE_AWARDED_PROVENANCE")
    for r in crm_q(
        f"""
        SELECT COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where}
          AND source_awarded_table IS NOT NULL
        """
    ):
        print(dict(r))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
