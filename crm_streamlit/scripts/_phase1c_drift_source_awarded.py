#!/usr/bin/env python3
"""Phase 1c: drift reconcile + source-awarded vs CRM-open mismatches."""
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


def q(db, sql, params=None):
    rows = db.execute_query(sql, params if params is not None else None)
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(r)
        else:
            # RealDict or tuple
            try:
                out.append(dict(r))
            except Exception:
                out.append(r)
    return out


def main() -> int:
    _, tender, crm, _ = connect_databases()
    where = (
        "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND "
        + actionable_submission_sql("cp")
    )
    total = q(crm, f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {where}")[0]["c"]
    created_today = q(
        crm,
        f"""
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE {where} AND date(crm_created_at)=CURRENT_DATE
        """,
    )[0]["c"]
    stock = total - created_today
    print("FINAL_UI_TORGI=", total)
    print("CREATED_TODAY_IN_UI=", created_today)
    print("STOCK_BEFORE_TODAY=", stock)
    print("OLD_OBSERVED_APPROX=1829")
    print("DELTA_TODAY=", total - 1829)
    print("RECONCILE_STOCK_PLUS_TODAY=", stock + created_today)

    # Null deadline among ALL submission_open (not just UI)
    print("\n=== SUBMISSION_OPEN_DEADLINE_BREAKDOWN ===")
    for r in q(
        crm,
        """
        SELECT
          COUNT(*) AS submission_open,
          COUNT(*) FILTER (WHERE end_date IS NULL) AS null_end,
          COUNT(*) FILTER (WHERE end_date < CURRENT_DATE) AS past_end,
          COUNT(*) FILTER (
            WHERE end_date >= CURRENT_DATE
              AND end_date < CURRENT_DATE + INTERVAL '2 days'
          ) AS short_window,
          COUNT(*) FILTER (
            WHERE end_date >= CURRENT_DATE + INTERVAL '2 days'
          ) AS actionable_window
        FROM crm_procurements
        WHERE crm_stage='torgi' AND award_status='submission_open'
        """,
    ):
        print(r)

    # Source tables inventory
    print("\n=== SOURCE_TABLES ===")
    tables = q(
        tender,
        """
        SELECT table_name::text AS table_name
        FROM information_schema.tables
        WHERE table_schema='public'
          AND (
            table_name ILIKE '%%44%%fz%%'
            OR table_name ILIKE '%%223%%fz%%'
            OR table_name ILIKE '%%615%%'
            OR table_name ILIKE 'torgi%%'
          )
        ORDER BY 1
        """,
    )
    for trow in tables:
        t = trow["table_name"] if isinstance(trow, dict) else trow[0]
        try:
            c = q(tender, f"SELECT COUNT(*) AS c FROM {t}")[0]["c"]
            print(f"{t}={c}")
        except Exception as exc:
            print(f"{t}=ERR:{type(exc).__name__}:{exc}")

    # Cross-check: CRM actionable open CNs present in source awarded tables
    print("\n=== CRM_OPEN_IN_SOURCE_AWARDED ===")
    for open_t, awarded_t, law in (
        ("reestr_contract_44_fz", "reestr_contract_44_fz_awarded", "44"),
        ("reestr_contract_223_fz", "reestr_contract_223_fz_awarded", "223"),
    ):
        # discover number column on awarded
        cols = [
            (r["column_name"] if isinstance(r, dict) else r[0])
            for r in q(
                tender,
                """
                SELECT column_name::text AS column_name
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s
                """,
                (awarded_t,),
            )
        ]
        print(f"{awarded_t} cols_sample=", [c for c in cols if "reg" in c.lower() or "number" in c.lower() or "notice" in c.lower()][:20])
        num_col = None
        for cand in (
            "registration_number",
            "purchase_number",
            "notice_number",
            "contract_reg_number",
            "reestr_number",
        ):
            if cand in cols:
                num_col = cand
                break
        if not num_col:
            print(f"{law}_AWARDED_NUMBER_COL=NOT_FOUND")
            continue
        # CRM open actionable from that law
        crm_open = q(
            crm,
            f"""
            SELECT btrim(contract_number) AS cn
            FROM crm_procurements cp
            WHERE {where}
              AND source_table=%s
              AND contract_number IS NOT NULL AND btrim(contract_number)<>''
            """,
            (open_t,),
        )
        cns = [r["cn"] for r in crm_open]
        print(f"{law}_CRM_OPEN_ACTIONABLE_WITH_CN=", len(cns))
        if not cns:
            continue
        # chunk check
        hits = 0
        samples = []
        for i in range(0, len(cns), 500):
            chunk = cns[i : i + 500]
            found = q(
                tender,
                f"""
                SELECT DISTINCT {num_col}::text AS cn
                FROM {awarded_t}
                WHERE {num_col}::text = ANY(%s)
                """,
                (chunk,),
            )
            hits += len(found)
            for r in found[:3]:
                samples.append(r["cn"])
        print(f"{law}_OPEN_ALSO_IN_SOURCE_AWARDED=", hits)
        print(f"{law}_SAMPLES=", samples[:5])

    # Also commission source
    print("\n=== CRM_OPEN_IN_SOURCE_COMMISSION ===")
    for open_t, commission_t, law in (
        ("reestr_contract_44_fz", "reestr_contract_44_fz_commission_work", "44"),
        ("reestr_contract_223_fz", "reestr_contract_223_fz_commission_work", "223"),
    ):
        cols = [
            (r["column_name"] if isinstance(r, dict) else r[0])
            for r in q(
                tender,
                """
                SELECT column_name::text AS column_name
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s
                """,
                (commission_t,),
            )
        ]
        num_col = None
        for cand in (
            "registration_number",
            "purchase_number",
            "notice_number",
            "contract_reg_number",
            "reestr_number",
        ):
            if cand in cols:
                num_col = cand
                break
        if not num_col:
            print(f"{law}_COMMISSION_NUMBER_COL=NOT_FOUND cols=", cols[:15])
            continue
        crm_open = q(
            crm,
            f"""
            SELECT btrim(contract_number) AS cn
            FROM crm_procurements cp
            WHERE {where}
              AND source_table=%s
              AND contract_number IS NOT NULL AND btrim(contract_number)<>''
            """,
            (open_t,),
        )
        cns = [r["cn"] for r in crm_open]
        hits = 0
        for i in range(0, len(cns), 500):
            chunk = cns[i : i + 500]
            found = q(
                tender,
                f"SELECT DISTINCT {num_col}::text AS cn FROM {commission_t} WHERE {num_col}::text = ANY(%s)",
                (chunk,),
            )
            hits += len(found)
        print(f"{law}_OPEN_ALSO_IN_SOURCE_COMMISSION=", hits, "NUM_COL=", num_col)

    # Today's new rows deadline quality
    print("\n=== TODAY_NEW_DEADLINE_STATS ===")
    for r in q(
        crm,
        f"""
        SELECT
          COUNT(*) AS c,
          MIN(end_date) AS min_end,
          MAX(end_date) AS max_end,
          COUNT(*) FILTER (WHERE end_date > CURRENT_DATE + INTERVAL '365 days') AS over_365
        FROM crm_procurements cp
        WHERE {where} AND date(crm_created_at)=CURRENT_DATE
        """,
    ):
        print(r)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
