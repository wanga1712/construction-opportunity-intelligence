#!/usr/bin/env python3
"""Phase 0/1 READ-ONLY audit: torgi count pipeline + lifecycle collisions."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from src.bootstrap import setup_source_path

setup_source_path()

from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.db_bootstrap import connect_databases
from src.services.commercial_routing_v3.projection import (
    normalize_contract_number,
    resolve_lifecycle_identity,
    stage_from_source_table,
)


def q(crm, sql, params=None):
    return crm.execute_query(sql, params or ())


def main() -> int:
    _, tender, crm, warn = connect_databases()
    print("WARN", warn)

    # --- CRM raw by stage/status/source ---
    print("\n=== CRM_GROUP_BY_SOURCE_STAGE_STATUS ===")
    rows = q(
        crm,
        """
        SELECT COALESCE(source_table,'(null)') AS source_table,
               COALESCE(crm_stage,'(null)') AS crm_stage,
               COALESCE(award_status,'(null)') AS award_status,
               COUNT(*) AS c
        FROM crm_procurements
        GROUP BY 1,2,3
        ORDER BY c DESC
        """,
    )
    for r in rows or []:
        print(f"{r['c']:6d}  {r['source_table'][:50]:50s}  {r['crm_stage']:12s}  {r['award_status']}")

    print("\n=== CRM_STAGE_ROLLUP ===")
    for r in q(
        crm,
        """
        SELECT crm_stage, award_status, COUNT(*) AS c
        FROM crm_procurements
        GROUP BY 1,2 ORDER BY 1,2
        """,
    ) or []:
        print(dict(r))

    # Exact UI workset path for Идут торги
    where_torgi = (
        "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND "
        + actionable_submission_sql("cp")
    )
    raw_torgi = q(
        crm,
        f"SELECT COUNT(*) AS c FROM crm_procurements cp WHERE {where_torgi}",
    )[0]["c"]
    raw_torgi_no_window = q(
        crm,
        """
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE cp.crm_stage='torgi' AND cp.award_status='submission_open'
        """,
    )[0]["c"]
    raw_torgi_null_end = q(
        crm,
        """
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE cp.crm_stage='torgi' AND cp.award_status='submission_open'
          AND cp.end_date IS NULL
        """,
    )[0]["c"]
    raw_torgi_past = q(
        crm,
        """
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE cp.crm_stage='torgi' AND cp.award_status='submission_open'
          AND cp.end_date IS NOT NULL
          AND cp.end_date < CURRENT_DATE
        """,
    )[0]["c"]
    raw_torgi_short_window = q(
        crm,
        """
        SELECT COUNT(*) AS c FROM crm_procurements cp
        WHERE cp.crm_stage='torgi' AND cp.award_status='submission_open'
          AND cp.end_date IS NOT NULL
          AND cp.end_date < CURRENT_DATE + INTERVAL '2 days'
          AND cp.end_date >= CURRENT_DATE
        """,
    )[0]["c"]

    print("\n=== UI_TORGI_PIPELINE ===")
    print("RAW_SUBMISSION_OPEN=", raw_torgi_no_window)
    print("NULL_END_IN_SUBMISSION_OPEN=", raw_torgi_null_end)
    print("PAST_END_IN_SUBMISSION_OPEN=", raw_torgi_past)
    print("SHORT_WINDOW_0_1DAY_IN_SUBMISSION_OPEN=", raw_torgi_short_window)
    print("AFTER_ACTIONABLE_WINDOW_SQL=", raw_torgi)
    print("FINAL_UI_TOTAL_MATCHES_WORKSET_IDS=", raw_torgi)

    # Law breakdown of actionable torgi
    print("\n=== UI_TORGI_BY_SOURCE_TABLE ===")
    for r in q(
        crm,
        f"""
        SELECT source_table, COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where_torgi}
        GROUP BY 1 ORDER BY c DESC
        """,
    ) or []:
        print(f"{r['c']:6d}  {r['source_table']}")

    # Commission / awarded raw
    commission = q(
        crm,
        """
        SELECT COUNT(*) AS c FROM crm_procurements
        WHERE crm_stage='torgi'
          AND award_status IN ('submission_closed_waiting_award','award_not_found')
        """,
    )[0]["c"]
    commission_alt = q(
        crm,
        """
        SELECT COUNT(*) AS c FROM crm_procurements
        WHERE crm_stage='commission' OR award_status IN ('commission')
        """,
    )[0]["c"]
    awarded = q(
        crm,
        "SELECT COUNT(*) AS c FROM crm_procurements WHERE crm_stage='razygranye'",
    )[0]["c"]
    print("\nCRM_COMMISSION_UI_PATH=", commission)
    print("CRM_COMMISSION_ALT=", commission_alt)
    print("CRM_AWARDED_RAW=", awarded)

    # Identity collisions: same contract_number across different stages
    print("\n=== LOGICAL_IDENTITY_COLLISIONS ===")
    collisions = q(
        crm,
        """
        WITH norm AS (
          SELECT id, source_table, source_id, crm_stage, award_status, end_date,
                 btrim(contract_number) AS cn,
                 CASE
                   WHEN source_table ILIKE '%223%' THEN '223'
                   WHEN source_table ILIKE '%615%' THEN '615'
                   WHEN source_table ILIKE '%44%' THEN '44'
                   ELSE 'OTHER'
                 END AS law
          FROM crm_procurements
          WHERE contract_number IS NOT NULL AND btrim(contract_number) <> ''
        ),
        multi AS (
          SELECT law, cn, COUNT(*) AS rows_c,
                 COUNT(DISTINCT crm_stage) AS stages_c,
                 COUNT(DISTINCT source_table) AS tables_c,
                 array_agg(DISTINCT crm_stage) AS stages,
                 array_agg(DISTINCT source_table) AS tables
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

    # OPEN submission_open rows whose same CN also has awarded
    open_awarded_in_torgi = q(
        crm,
        f"""
        WITH awarded_cn AS (
          SELECT DISTINCT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%223%' THEN '223'
                      WHEN source_table ILIKE '%615%' THEN '615'
                      WHEN source_table ILIKE '%44%' THEN '44'
                      ELSE 'OTHER' END AS law
          FROM crm_procurements
          WHERE crm_stage='razygranye'
            AND contract_number IS NOT NULL AND btrim(contract_number) <> ''
        )
        SELECT COUNT(*) AS c
        FROM crm_procurements cp
        JOIN awarded_cn a
          ON a.cn = btrim(cp.contract_number)
         AND a.law = CASE WHEN cp.source_table ILIKE '%223%' THEN '223'
                          WHEN cp.source_table ILIKE '%615%' THEN '615'
                          WHEN cp.source_table ILIKE '%44%' THEN '44'
                          ELSE 'OTHER' END
        WHERE {where_torgi}
        """,
    )[0]["c"]
    print("ACTIONABLE_TORGI_WITH_AWARDED_SIBLING=", open_awarded_in_torgi)

    open_commission_sibling = q(
        crm,
        f"""
        WITH waiting_cn AS (
          SELECT DISTINCT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%223%' THEN '223'
                      WHEN source_table ILIKE '%615%' THEN '615'
                      WHEN source_table ILIKE '%44%' THEN '44'
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
         AND w.law = CASE WHEN cp.source_table ILIKE '%223%' THEN '223'
                          WHEN cp.source_table ILIKE '%615%' THEN '615'
                          WHEN cp.source_table ILIKE '%44%' THEN '44'
                          ELSE 'OTHER' END
        WHERE {where_torgi}
        """,
    )[0]["c"]
    print("ACTIONABLE_TORGI_WITH_COMMISSION_SIBLING=", open_commission_sibling)

    # Sample collisions
    print("\n=== SAMPLE_OPEN_AWARDED_COLLISIONS ===")
    samples = q(
        crm,
        f"""
        WITH awarded_cn AS (
          SELECT btrim(contract_number) AS cn,
                 CASE WHEN source_table ILIKE '%223%' THEN '223'
                      WHEN source_table ILIKE '%615%' THEN '615'
                      WHEN source_table ILIKE '%44%' THEN '44'
                      ELSE 'OTHER' END AS law,
                 MIN(id) AS awarded_id,
                 MIN(source_table) AS awarded_table
          FROM crm_procurements
          WHERE crm_stage='razygranye'
            AND contract_number IS NOT NULL AND btrim(contract_number) <> ''
          GROUP BY 1,2
        )
        SELECT cp.id, cp.contract_number, cp.source_table, cp.end_date,
               a.awarded_id, a.awarded_table, left(cp.auction_name,60) AS title
        FROM crm_procurements cp
        JOIN awarded_cn a
          ON a.cn = btrim(cp.contract_number)
         AND a.law = CASE WHEN cp.source_table ILIKE '%223%' THEN '223'
                          WHEN cp.source_table ILIKE '%615%' THEN '615'
                          WHEN cp.source_table ILIKE '%44%' THEN '44'
                          ELSE 'OTHER' END
        WHERE {where_torgi}
        ORDER BY cp.end_date NULLS LAST
        LIMIT 8
        """,
    )
    for r in samples or []:
        print(dict(r))

    # Created_at buckets for drift attribution among actionable
    print("\n=== ACTIONABLE_TORGI_BY_CREATED_DAY ===")
    for r in q(
        crm,
        f"""
        SELECT date(crm_created_at) AS d, COUNT(*) AS c
        FROM crm_procurements cp
        WHERE {where_torgi}
        GROUP BY 1 ORDER BY 1 DESC NULLS LAST
        LIMIT 15
        """,
    ) or []:
        print(dict(r))

    # Source DB counts if tender connection works
    print("\n=== SOURCE_TABLE_COUNTS ===")
    source_tables = [
        ("SOURCE_44_OPEN", "reestr_contract_44_fz"),
        ("SOURCE_44_COMMISSION", "reestr_contract_44_fz_commission_work"),
        ("SOURCE_44_AWARDED", "reestr_contract_44_fz_awarded"),
        ("SOURCE_223_OPEN", "reestr_contract_223_fz"),
        ("SOURCE_223_COMMISSION", "reestr_contract_223_fz_commission_work"),
        ("SOURCE_223_AWARDED", "reestr_contract_223_fz_awarded"),
        ("SOURCE_615_OPEN", "torgi_615_pp"),
        ("SOURCE_615_COMMISSION", None),
        ("SOURCE_615_AWARDED", None),
    ]
    # Also probe alternate names
    alt = q(
        tender,
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public'
          AND (
            table_name ILIKE '%44%fz%'
            OR table_name ILIKE '%223%fz%'
            OR table_name ILIKE '%615%'
            OR table_name ILIKE 'notice%'
            OR table_name ILIKE 'procurements%'
          )
        ORDER BY 1
        """,
    )
    print("SOURCE_CANDIDATE_TABLES=")
    for r in alt or []:
        print(" ", r["table_name"])

    for label, table in source_tables:
        if not table:
            print(f"{label}=NOT_AVAILABLE")
            continue
        try:
            c = q(tender, f"SELECT COUNT(*) AS c FROM {table}")[0]["c"]
            print(f"{label}={c} TABLE={table}")
        except Exception as exc:
            print(f"{label}=NOT_AVAILABLE ERR={type(exc).__name__}:{exc}")

    # Control notice
    print("\n=== CONTROL_32515489436 ===")
    for r in q(
        crm,
        """
        SELECT id, source_table, source_id, crm_stage, award_status, end_date,
               contract_number, left(auction_name,80) AS title
        FROM crm_procurements WHERE contract_number=%s
        """,
        ("32515489436",),
    ) or []:
        print(dict(r))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
