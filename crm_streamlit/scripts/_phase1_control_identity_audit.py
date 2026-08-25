#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/pythonProject89")
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.torgi_publication import (
    publication_schema_ready,
    torgi_publication_sql_filters,
)


def main() -> int:
    _, tender, crm, warn = connect_databases()
    out = {"db_warn": warn}
    cols = crm.execute_query(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'crm_procurement_category_opportunities'
        ORDER BY ordinal_position
        """
    )
    out["opp_columns"] = [c["column_name"] for c in cols]

    rows = crm.execute_query(
        """
        SELECT cp.id, cp.source_table, cp.source_id, cp.contract_number,
               cp.tender_link, cp.start_date, cp.end_date, cp.delivery_end_date,
               cp.source_updated_at, cp.crm_updated_at, cp.auction_name,
               cp.initial_price, cp.customer, cp.delivery_region,
               cp.okpd_code, cp.okpd_name, cp.award_status, cp.crm_stage,
               cp.ai_assessment_status
        FROM crm_procurements cp
        WHERE cp.contract_number = %s
           OR cp.auction_name ILIKE %s
           OR cp.tender_link ILIKE %s
        ORDER BY cp.id
        LIMIT 20
        """,
        ("32616311665", "%камер видеонаблюдения%ДОУ%8%", "%20167502%"),
    )
    out["control_candidates"] = rows
    if not rows:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 1

    control = next(
        (r for r in rows if str(r.get("contract_number") or "") == "32616311665"),
        rows[0],
    )
    cid = control["id"]
    out["CONTROL"] = control

    ai = crm.execute_query(
        """
        SELECT id, assessment_version, status, is_current,
               proposed_route_profile, proposed_object_type,
               proposed_procurement_type, confidence, reasons,
               normalized_result, inference_run_id
        FROM procurement_ai_assessments
        WHERE procurement_id = %s AND is_current = TRUE
        LIMIT 1
        """,
        (cid,),
    )
    out["CONTROL_AI"] = ai[0] if ai else None

    # Use only columns that exist.
    opp_cols = set(out["opp_columns"])
    select_bits = ["status"]
    for c in (
        "commercial_category_code",
        "category_code",
        "subcategory_code",
        "opportunity_track",
        "candidate_medal",
        "candidate_score",
        "commercial_state",
        "confirmed_base_medal",
        "research_action",
    ):
        if c in opp_cols:
            select_bits.append(c)
    opps = crm.execute_query(
        f"""
        SELECT {", ".join(select_bits)}
        FROM crm_procurement_category_opportunities
        WHERE procurement_id = %s AND status = 'CURRENT'
        """,
        (cid,),
    )
    out["CONTROL_OPPS"] = opps

    pub_visible = False
    if publication_schema_ready(crm):
        pub = torgi_publication_sql_filters()
        vis = crm.execute_query(
            f"""
            SELECT 1 AS ok
            FROM crm_procurements cp
            WHERE cp.id = %s
              AND cp.crm_stage = 'torgi'
              AND cp.award_status = 'submission_open'
              AND cp.end_date >= CURRENT_DATE
              {pub}
            LIMIT 1
            """,
            (cid,),
        )
        pub_visible = bool(vis)
    out["CONTROL_PUBLICATION_VISIBLE"] = pub_visible

    # S7 source
    s7 = None
    src_table = control.get("source_table")
    src_id = control.get("source_id")
    try:
        if tender and src_table and src_id is not None:
            allowed = {
                "reestr_contract_223_fz",
                "reestr_contract_44_fz",
                "notifications_44_fz",
            }
            if src_table in allowed:
                s7_rows = tender.execute_query(
                    f"SELECT * FROM {src_table} WHERE id = %s LIMIT 1",
                    (src_id,),
                )
                if s7_rows:
                    row = dict(s7_rows[0])
                    out["S7_ALL_COLUMNS"] = sorted(row.keys())
                    keep = [
                        k
                        for k in row.keys()
                        if any(
                            x in k.lower()
                            for x in (
                                "contract",
                                "notice",
                                "reg",
                                "link",
                                "url",
                                "date",
                                "end",
                                "start",
                                "close",
                                "purchase",
                                "number",
                                "id",
                                "name",
                                "title",
                                "okpd",
                                "price",
                                "customer",
                                "xml",
                                "raw",
                            )
                        )
                    ]
                    s7 = {k: row.get(k) for k in keep}
    except Exception as exc:
        out["S7_ERROR"] = str(exc)
    out["S7_SOURCE"] = s7

    # Link stats open
    for law, like in (("223", "%223%"), ("44", "%44%")):
        stats = crm.execute_query(
            """
            SELECT
              count(*) AS total,
              count(*) FILTER (WHERE tender_link ILIKE '%%zakupki.gov.ru/epz/%%') AS public_epz,
              count(*) FILTER (WHERE tender_link ILIKE '%%lk.zakupki.gov.ru%%') AS private_lk,
              count(*) FILTER (
                WHERE tender_link IS NOT NULL AND tender_link <> ''
                  AND tender_link NOT ILIKE '%%zakupki.gov.ru/epz/%%'
                  AND tender_link NOT ILIKE '%%lk.zakupki.gov.ru%%'
              ) AS other,
              count(*) FILTER (WHERE tender_link IS NULL OR tender_link = '') AS null_link
            FROM crm_procurements
            WHERE crm_stage = 'torgi'
              AND award_status = 'submission_open'
              AND end_date >= CURRENT_DATE
              AND source_table ILIKE %s
            """,
            (like,),
        )
        out[f"LINK_STATS_{law}_OPEN"] = stats[0] if stats else None

    # Commission / awarded private LK counts
    for stage, key in (("commission", "COMMISSION"), ("awarded", "AWARDED")):
        for law, like in (("223", "%223%"), ("44", "%44%")):
            stats = crm.execute_query(
                """
                SELECT count(*) AS n
                FROM crm_procurements
                WHERE crm_stage = %s
                  AND source_table ILIKE %s
                  AND tender_link ILIKE '%%lk.zakupki.gov.ru%%'
                """,
                (stage, like),
            )
            out[f"AFFECTED_{key}_{law}_PRIVATE_LK"] = (
                stats[0]["n"] if stats else None
            )

    buckets = crm.execute_query(
        """
        SELECT
          CASE
            WHEN end_date <= CURRENT_DATE + 30 THEN 'WITHIN_30'
            WHEN end_date <= CURRENT_DATE + 90 THEN '31_90'
            WHEN end_date <= CURRENT_DATE + 180 THEN '91_180'
            WHEN end_date <= CURRENT_DATE + 365 THEN '181_365'
            ELSE 'OVER_365'
          END AS bucket,
          CASE
            WHEN source_table ILIKE '%44%' THEN '44'
            WHEN source_table ILIKE '%223%' THEN '223'
            ELSE 'OTHER'
          END AS law,
          count(*) AS n
        FROM crm_procurements
        WHERE crm_stage = 'torgi'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )
    out["DEADLINE_BUCKETS"] = buckets
    out["FARTHEST_50"] = crm.execute_query(
        """
        SELECT id, source_table, contract_number, end_date, tender_link,
               left(auction_name, 120) AS title, initial_price
        FROM crm_procurements
        WHERE crm_stage = 'torgi'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE
        ORDER BY end_date DESC NULLS LAST, id DESC
        LIMIT 50
        """
    )

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
