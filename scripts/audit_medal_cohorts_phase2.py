#!/usr/bin/env python3
"""Read-only Phase 2 cohort discovery for medal recalibration."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

THRESHOLDS = (5, 10, 20, 30)


def crm_dsn() -> dict:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


DIRECT_BASE = """
WITH base AS (
    SELECT o.procurement_id,
           o.commercial_category_code AS category,
           NULLIF(o.expected_category_value, 0) AS category_value,
           NULLIF(p.initial_price, 0) AS procurement_value,
           p.okpd_code,
           CASE WHEN p.okpd_code ~ '^[0-9]+[.][0-9]+' THEN split_part(p.okpd_code, '.', 1) END AS okpd2,
           CASE WHEN p.okpd_code ~ '^[0-9]+[.][0-9]+[.][0-9]+'
                THEN split_part(p.okpd_code, '.', 1) || '.' || split_part(p.okpd_code, '.', 2) END AS okpd3,
           CASE WHEN p.okpd_code ~ '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+'
                THEN split_part(p.okpd_code, '.', 1) || '.' ||
                     split_part(p.okpd_code, '.', 2) || '.' ||
                     split_part(p.okpd_code, '.', 3) END AS okpd4
      FROM crm_procurement_category_opportunities o
      JOIN crm_procurements p ON p.id = o.procurement_id
     WHERE o.status = 'CURRENT'
       AND o.opportunity_track = 'DIRECT_SUPPLY'
)
SELECT *,
       COALESCE(category_value, procurement_value) AS value,
       CASE WHEN category_value IS NOT NULL THEN 'DIRECT_PROCUREMENT_VALUE'
            WHEN procurement_value IS NOT NULL THEN 'DIRECT_NMCK_FALLBACK'
            ELSE 'VALUE_UNKNOWN' END AS value_source
  FROM base
"""


def direct_stats(cur, level: str) -> List[Dict[str, Any]]:
    if level == "global":
        key_sql = "'GLOBAL_DIRECT'"
        group_sql = "GROUP BY 1"
    else:
        key_sql = f"category || '|' || COALESCE({level}, 'NULL')"
        group_sql = "GROUP BY 1, category"
    sql = f"""
        WITH b AS ({DIRECT_BASE})
        SELECT {key_sql} AS cohort_key,
               count(*) AS n,
               min(value) AS min,
               percentile_cont(0.10) WITHIN GROUP (ORDER BY value) AS p10,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY value) AS p25,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY value) AS median,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY value) AS p75,
               percentile_cont(0.90) WITHIN GROUP (ORDER BY value) AS p90,
               max(value) AS max,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY value)
                 - percentile_cont(0.25) WITHIN GROUP (ORDER BY value) AS iqr
          FROM b
         WHERE value IS NOT NULL
         {group_sql}
         ORDER BY n DESC, cohort_key
    """
    cur.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def direct_value_source(cur) -> List[Dict[str, Any]]:
    cur.execute(
        f"""
        WITH b AS ({DIRECT_BASE})
        SELECT value_source, count(*) AS n
          FROM b GROUP BY value_source ORDER BY n DESC
        """
    )
    return [dict(r) for r in cur.fetchall()]


def embedded_audit(cur) -> Dict[str, Any]:
    cur.execute(
        """
        WITH e AS (
            SELECT o.*, p.initial_price,
                   CASE WHEN o.expected_category_value IS NOT NULL
                         AND o.expected_category_value = p.initial_price
                        THEN NULL
                        ELSE NULLIF(o.expected_category_value, 0) END AS valid_value
              FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT'
               AND o.opportunity_track = 'EMBEDDED_MATERIAL'
        ),
        oc AS (
            SELECT c.procurement_id, max(c.object_type) AS object_type
              FROM crm_procurement_object_classifications c
             WHERE c.is_current
             GROUP BY c.procurement_id
        ),
        mat AS (
            SELECT pc.procurement_id,
                   count(*) FILTER (WHERE COALESCE(pc.material, '') <> '') AS material_count,
                   count(DISTINCT pc.material) FILTER (WHERE COALESCE(pc.material, '') <> '') AS material_distinct
              FROM crm_procurement_product_candidates pc
             WHERE pc.is_current
             GROUP BY pc.procurement_id
        ),
        qty AS (
            SELECT pf.procurement_id,
                   count(*) FILTER (WHERE pf.quantity IS NOT NULL) AS quantity_count,
                   count(DISTINCT pf.unit) FILTER (WHERE pf.quantity IS NOT NULL AND COALESCE(pf.unit,'') <> '') AS unit_count
              FROM crm_v3_product_findings pf
             GROUP BY pf.procurement_id
        )
        SELECT count(*) AS total,
               count(*) FILTER (WHERE e.valid_value IS NOT NULL) AS valid_category_value,
               count(*) FILTER (WHERE e.expected_category_value IS NOT NULL AND e.valid_value IS NULL) AS invalid_excluded,
               count(*) FILTER (WHERE oc.object_type IS NOT NULL) AS with_object_type,
               count(*) FILTER (WHERE COALESCE(mat.material_count,0) > 0) AS with_material,
               count(*) FILTER (WHERE COALESCE(qty.quantity_count,0) > 0) AS with_quantity,
               count(*) FILTER (WHERE COALESCE(qty.unit_count,0) > 0) AS with_unit
          FROM e
          LEFT JOIN oc ON oc.procurement_id = e.procurement_id
          LEFT JOIN mat ON mat.procurement_id = e.procurement_id
          LEFT JOIN qty ON qty.procurement_id = e.procurement_id
        """
    )
    return dict(cur.fetchone())


def embedded_object_types(cur) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT COALESCE(c.object_type, 'NULL') AS object_type, count(*) AS n
          FROM crm_procurement_category_opportunities o
          LEFT JOIN crm_procurement_object_classifications c
            ON c.procurement_id = o.procurement_id AND c.is_current
         WHERE o.status='CURRENT' AND o.opportunity_track='EMBEDDED_MATERIAL'
         GROUP BY 1 ORDER BY n DESC LIMIT 20
        """
    )
    return [dict(r) for r in cur.fetchall()]


def embedded_quantity_cohorts(cur) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT o.commercial_category_code AS category,
               COALESCE(c.object_type, 'NULL') AS object_type,
               COALESCE(pf.unit, 'NULL') AS unit,
               count(*) AS n,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY pf.quantity) AS p25,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY pf.quantity) AS median,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY pf.quantity) AS p75
          FROM crm_v3_product_findings pf
          JOIN crm_procurement_category_opportunities o
            ON o.procurement_id = pf.procurement_id
           AND o.commercial_category_code = pf.category_code
           AND o.status='CURRENT'
           AND o.opportunity_track='EMBEDDED_MATERIAL'
          LEFT JOIN crm_procurement_object_classifications c
            ON c.procurement_id = pf.procurement_id AND c.is_current
         WHERE pf.quantity IS NOT NULL AND COALESCE(pf.unit,'') <> ''
         GROUP BY 1,2,3
         HAVING count(*) >= 2
         ORDER BY n DESC LIMIT 30
        """
    )
    return [dict(r) for r in cur.fetchall()]


def fmt_num(value: Any) -> str:
    if value is None:
        return "NULL"
    return f"{float(value):.2f}"


def main() -> int:
    conn = psycopg2.connect(**crm_dsn())
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            print("DIRECT_VALUE_SOURCE")
            for row in direct_value_source(cur):
                print(f"{row['value_source']}={row['n']}")

            levels = ("okpd4", "okpd3", "okpd2", "category", "global")
            all_stats: Dict[str, List[Dict[str, Any]]] = {}
            for level in levels:
                all_stats[level] = direct_stats(cur, level)
                print(f"\nDIRECT_LEVEL={level.upper()}")
                for row in all_stats[level][:40]:
                    print(
                        f"{row['cohort_key']}|N={row['n']}|"
                        f"min={fmt_num(row['min'])}|p10={fmt_num(row['p10'])}|"
                        f"p25={fmt_num(row['p25'])}|median={fmt_num(row['median'])}|"
                        f"p75={fmt_num(row['p75'])}|p90={fmt_num(row['p90'])}|"
                        f"max={fmt_num(row['max'])}|iqr={fmt_num(row['iqr'])}"
                    )

            print("\nDIRECT_COVERAGE_BY_MIN_N")
            for level in levels[:-1]:
                for threshold in THRESHOLDS:
                    eligible = [r for r in all_stats[level] if int(r["n"]) >= threshold]
                    covered = sum(int(r["n"]) for r in eligible)
                    total = sum(int(r["n"]) for r in all_stats[level])
                    print(
                        f"level={level}|min_n={threshold}|cohorts={len(eligible)}|"
                        f"covered_opportunities={covered}|total={total}"
                    )

            emb = embedded_audit(cur)
            print("\nEMBEDDED")
            for key, value in emb.items():
                print(f"{key}={value}")
            print("EMBEDDED_TOP_OBJECT_TYPES")
            for row in embedded_object_types(cur):
                print(f"{row['object_type']}|N={row['n']}")
            print("EMBEDDED_QUANTITY_COHORTS")
            for row in embedded_quantity_cohorts(cur):
                print(
                    f"{row['category']}|{row['object_type']}|{row['unit']}|"
                    f"N={row['n']}|p25={fmt_num(row['p25'])}|"
                    f"median={fmt_num(row['median'])}|p75={fmt_num(row['p75'])}"
                )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
