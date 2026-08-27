#!/usr/bin/env python3
"""Phase 1 continuation: collisions + source counts + drift buckets (READ-ONLY)."""
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


def q(crm, sql, params=None):
    return crm.execute_query(sql, params if params is not None else None)


def main() -> int:
    _, tender, crm, warn = connect_databases()
    print("WARN", warn)
    where_torgi = (
        "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND "
        + actionable_submission_sql("cp")
    )

    print("FINAL_UI_TORGI=", q(crm, f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {where_torgi}")[0]["c"])

    print("\n=== ACTIONABLE_BY_CREATED_DAY ===")
    for r in q(
        crm,
        f"""
        SELECT date(crm_created_at) AS d, COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where_torgi}
        GROUP BY 1 ORDER BY 1 DESC NULLS LAST
        LIMIT 20
        """,
    ) or []:
        print(dict(r))

    print("\n=== ACTIONABLE_BY_UPDATED_DAY ===")
    for r in q(
        crm,
        f"""
        SELECT date(crm_updated_at) AS d, COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where_torgi}
        GROUP BY 1 ORDER BY 1 DESC NULLS LAST
        LIMIT 20
        """,
    ) or []:
        print(dict(r))

    # Law buckets for actionable
    print("\n=== ACTIONABLE_BY_LAW ===")
    for r in q(
        crm,
        f"""
        SELECT CASE
                 WHEN source_table ILIKE '%%223%%' THEN '223'
                 WHEN source_table ILIKE '%%615%%' THEN '615'
                 WHEN source_table ILIKE '%%44%%' THEN '44'
                 ELSE 'OTHER'
               END AS law,
               COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where_torgi}
        GROUP BY 1 ORDER BY 1
        """,
    ) or []:
        print(dict(r))

    # Collisions using escaped %%
    print("\n=== LOGICAL_IDENTITY_COLLISIONS ===")
    collisions = q(
        crm,
        """
        WITH norm AS (
          SELECT id, source_table, source_id, crm_stage, award_status, end_date,
                 btrim(contract_number) AS cn,
                 CASE
                   WHEN source_table ILIKE '%%223%%' THEN '223'
                   WHEN source_table ILIKE '%%615%%' THEN '615'
                   WHEN source_table ILIKE '%%44%%' THEN '44'
                   ELSE 'OTHER'
                 END AS law
          FROM crm_procurements
          WHERE contract_number IS NOT NULL AND btrim(contract_number) <> ''
        ),
        multi AS (
          SELECT law, cn, COUNT(*) AS rows_c,
                 COUNT(DISTINCT crm_stage) AS stages_c,
                 COUNT(DISTINCT source_table) AS tables_c,
                 array_agg(DISTINCT crm_stage) AS stages
          FROM norm
          GROUP BY law, cn
          HAVING COUNT(*) > 1
        )
        SELECT
          COUNT(*) AS logical_multi_rows,
          COUNT(*) FILTER (WHERE stages_c > 1) AS multi_stage,
          COUNT(*) FILTER (
            WHERE 'torgi' = ANY(stages) AND 'razygranye' = ANY(stages)
          ) AS open_awarded,
          COUNT(*) FILTER (
            WHERE 'torgi' = ANY(stages) AND 'commission' = ANY(stages)
          ) AS open_commission,
          COUNT(*) FILTER (
            WHERE 'commission' = ANY(stages) AND 'razygranye' = ANY(stages)
          ) AS commission_awarded
        FROM multi
        """,
    )[0]
    print(dict(collisions))

    print("\n=== ACTIONABLE_TORGI_WITH_AWARDED_SIBLING ===")
    open_awarded = q(
        crm,
        f"""
        WITH awarded_cn AS (
          SELECT DISTINCT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%%223%%' THEN '223'
                      WHEN source_table ILIKE '%%615%%' THEN '615'
                      WHEN source_table ILIKE '%%44%%' THEN '44'
                      ELSE 'OTHER' END AS law
          FROM crm_procurements
          WHERE crm_stage='razygranye'
            AND contract_number IS NOT NULL AND btrim(contract_number) <> ''
        )
        SELECT COUNT(*) AS c
        FROM crm_procurements cp
        JOIN awarded_cn a
          ON a.cn = btrim(cp.contract_number)
         AND a.law = CASE WHEN cp.source_table ILIKE '%%223%%' THEN '223'
                          WHEN cp.source_table ILIKE '%%615%%' THEN '615'
                          WHEN cp.source_table ILIKE '%%44%%' THEN '44'
                          ELSE 'OTHER' END
        WHERE {where_torgi}
        """,
    )[0]["c"]
    print(open_awarded)

    print("\n=== ACTIONABLE_TORGI_WITH_COMMISSION_SIBLING ===")
    open_comm = q(
        crm,
        f"""
        WITH waiting_cn AS (
          SELECT DISTINCT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%%223%%' THEN '223'
                      WHEN source_table ILIKE '%%615%%' THEN '615'
                      WHEN source_table ILIKE '%%44%%' THEN '44'
                      ELSE 'OTHER' END AS law
          FROM crm_procurements
          WHERE (
              (crm_stage='torgi' AND award_status IN ('submission_closed_waiting_award','award_not_found'))
              OR crm_stage='commission'
            )
            AND contract_number IS NOT NULL AND btrim(contract_number) <> ''
        )
        SELECT COUNT(*) AS c
        FROM crm_procurements cp
        JOIN waiting_cn w
          ON w.cn = btrim(cp.contract_number)
         AND w.law = CASE WHEN cp.source_table ILIKE '%%223%%' THEN '223'
                          WHEN cp.source_table ILIKE '%%615%%' THEN '615'
                          WHEN cp.source_table ILIKE '%%44%%' THEN '44'
                          ELSE 'OTHER' END
        WHERE {where_torgi}
        """,
    )[0]["c"]
    print(open_comm)

    print("\n=== SAMPLE_OPEN_AWARDED ===")
    for r in q(
        crm,
        f"""
        WITH awarded_cn AS (
          SELECT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%%223%%' THEN '223'
                      WHEN source_table ILIKE '%%615%%' THEN '615'
                      WHEN source_table ILIKE '%%44%%' THEN '44'
                      ELSE 'OTHER' END AS law,
                 MIN(id) AS awarded_id,
                 MIN(source_table) AS awarded_table,
                 MIN(source_id) AS awarded_source_id
          FROM crm_procurements
          WHERE crm_stage='razygranye'
            AND contract_number IS NOT NULL AND btrim(contract_number) <> ''
          GROUP BY 1,2
        )
        SELECT cp.id AS open_id, cp.contract_number, cp.source_table AS open_table,
               cp.source_id AS open_source_id, cp.end_date,
               a.awarded_id, a.awarded_table, a.awarded_source_id,
               left(cp.auction_name,70) AS title
        FROM crm_procurements cp
        JOIN awarded_cn a
          ON a.cn = btrim(cp.contract_number)
         AND a.law = CASE WHEN cp.source_table ILIKE '%%223%%' THEN '223'
                          WHEN cp.source_table ILIKE '%%615%%' THEN '615'
                          WHEN cp.source_table ILIKE '%%44%%' THEN '44'
                          ELSE 'OTHER' END
        WHERE {where_torgi}
        ORDER BY cp.end_date NULLS LAST
        LIMIT 10
        """,
    ) or []:
        print(dict(r))

    # How many of the 2492 are "new" since a reference date if we can find ~1829
    # Reconstruct: actionable as of if we only count rows with end_date window AND
    # exclude those with awarded sibling
    print("\n=== COUNTERFACTUAL_AFTER_AWARDED_PRECEDENCE ===")
    after_awarded = q(
        crm,
        f"""
        WITH awarded_cn AS (
          SELECT DISTINCT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%%223%%' THEN '223'
                      WHEN source_table ILIKE '%%615%%' THEN '615'
                      WHEN source_table ILIKE '%%44%%' THEN '44'
                      ELSE 'OTHER' END AS law
          FROM crm_procurements
          WHERE crm_stage='razygranye'
            AND contract_number IS NOT NULL AND btrim(contract_number) <> ''
        )
        SELECT COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where_torgi}
          AND NOT EXISTS (
            SELECT 1 FROM awarded_cn a
            WHERE a.cn = btrim(cp.contract_number)
              AND a.law = CASE WHEN cp.source_table ILIKE '%%223%%' THEN '223'
                               WHEN cp.source_table ILIKE '%%615%%' THEN '615'
                               WHEN cp.source_table ILIKE '%%44%%' THEN '44'
                               ELSE 'OTHER' END
          )
        """,
    )[0]["c"]
    print("TORGI_AFTER_EXCLUDE_AWARDED_SIBLINGS=", after_awarded)

    # Source inventory
    print("\n=== SOURCE_TABLES ===")
    tables = [
        r["table_name"]
        for r in q(
            tender,
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public'
              AND (
                table_name ILIKE '%%44%%fz%%'
                OR table_name ILIKE '%%223%%fz%%'
                OR table_name ILIKE '%%615%%'
                OR table_name ILIKE 'notice%%'
                OR table_name ILIKE 'procurements%%'
                OR table_name ILIKE 'torgi%%'
              )
            ORDER BY 1
            """,
        )
        or []
    ]
    for t in tables:
        try:
            c = q(tender, f"SELECT COUNT(*) AS c FROM {t}")[0]["c"]
            print(f"{t}={c}")
        except Exception as exc:
            print(f"{t}=ERR:{type(exc).__name__}")

    # Source open with future deadline approx (if end_date column exists)
    print("\n=== SOURCE_OPEN_FUTURE_DEADLINE_PROBE ===")
    for t in ("reestr_contract_44_fz", "reestr_contract_223_fz"):
        try:
            cols = {
                r["column_name"]
                for r in q(
                    tender,
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s
                    """,
                    (t,),
                )
                or []
            }
            date_col = None
            for cand in ("end_date", "submission_close_date", "application_deadline", "deadline"):
                if cand in cols:
                    date_col = cand
                    break
            print(f"{t} COLS_HAVE_END=", "end_date" in cols, "DATE_COL=", date_col)
            if date_col:
                c = q(
                    tender,
                    f"SELECT COUNT(*) AS c FROM {t} WHERE {date_col} >= CURRENT_DATE + INTERVAL '2 days'",
                )[0]["c"]
                print(f"{t}_ACTIONABLE_BY_DATE={c}")
        except Exception as exc:
            print(t, type(exc).__name__, exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
