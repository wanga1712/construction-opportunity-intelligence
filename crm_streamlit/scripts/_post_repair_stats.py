#!/usr/bin/env python3
"""Post-repair CRM link / deadline / control stats (read-only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases
from src.services.procurement_identity import resolve_procurement_link


def classify(url: str | None) -> str:
    if not url:
        return "null"
    u = urlparse(url)
    host = (u.hostname or "").lower()
    path = (u.path or "").lower()
    if host == "lk.zakupki.gov.ru" and "/223/purchase/private/" in path:
        return "private_lk"
    if host == "zakupki.gov.ru" and "/epz/order/notice/" in path:
        return "public_epz"
    return "other"


def main() -> None:
    _, _, crm, _ = connect_databases()

    control = crm.execute_query(
        """
        SELECT id, contract_number, tender_link, end_date, award_status, crm_stage, source_table
        FROM crm_procurements WHERE id = 17758
        """
    )[0]
    view = resolve_procurement_link(
        source_table=control["source_table"],
        contract_number=control["contract_number"],
        tender_link=control["tender_link"],
    )

    rows = crm.execute_query(
        """
        SELECT award_status, tender_link, contract_number
        FROM crm_procurements WHERE source_table LIKE '%223%'
        """
    )
    stats = {
        "223_TOTAL": 0,
        "223_LINK_PUBLIC_EPZ": 0,
        "223_LINK_PRIVATE_LK": 0,
        "223_LINK_OTHER": 0,
        "223_LINK_NULL": 0,
    }
    by_stage: dict[str, dict[str, int]] = {}
    for r in rows:
        stats["223_TOTAL"] += 1
        c = classify(r["tender_link"])
        key = {
            "public_epz": "223_LINK_PUBLIC_EPZ",
            "private_lk": "223_LINK_PRIVATE_LK",
            "other": "223_LINK_OTHER",
            "null": "223_LINK_NULL",
        }[c]
        stats[key] += 1
        st = r["award_status"] or "NA"
        slot = by_stage.setdefault(
            st, {"public_epz": 0, "private_lk": 0, "other": 0, "null": 0, "n": 0}
        )
        slot[c] += 1
        slot["n"] += 1

    private_with_num = crm.execute_query(
        """
        SELECT COUNT(*) AS n FROM crm_procurements
        WHERE source_table LIKE '%223%'
          AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          AND NULLIF(TRIM(contract_number), '') IS NOT NULL
          AND contract_number NOT ILIKE 'MISSING-%'
        """
    )[0]["n"]
    private_without_num = crm.execute_query(
        """
        SELECT COUNT(*) AS n FROM crm_procurements
        WHERE source_table LIKE '%223%'
          AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          AND (
            NULLIF(TRIM(contract_number), '') IS NULL
            OR contract_number ILIKE 'MISSING-%'
          )
        """
    )[0]["n"]
    leftover_sample = crm.execute_query(
        """
        SELECT id, contract_number, tender_link, award_status
        FROM crm_procurements
        WHERE source_table LIKE '%223%'
          AND tender_link ILIKE '%lk.zakupki.gov.ru%'
        ORDER BY id
        LIMIT 15
        """
    )

    affected = crm.execute_query(
        """
        SELECT
          COUNT(*) FILTER (
            WHERE award_status = 'submission_open'
              AND source_table LIKE '%223%'
              AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          ) AS open_223_private,
          COUNT(*) FILTER (
            WHERE award_status = 'submission_open'
              AND source_table LIKE '%44%'
              AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          ) AS open_44_private,
          COUNT(*) FILTER (
            WHERE award_status IN ('submission_closed_waiting_award','award_not_found')
              AND source_table LIKE '%223%'
              AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          ) AS commission_223_private,
          COUNT(*) FILTER (
            WHERE award_status IN ('submission_closed_waiting_award','award_not_found')
              AND source_table LIKE '%44%'
              AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          ) AS commission_44_private,
          COUNT(*) FILTER (
            WHERE award_status = 'awarded'
              AND source_table LIKE '%223%'
              AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          ) AS awarded_223_private,
          COUNT(*) FILTER (
            WHERE award_status = 'awarded'
              AND source_table LIKE '%44%'
              AND tender_link ILIKE '%lk.zakupki.gov.ru%'
          ) AS awarded_44_private,
          COUNT(*) FILTER (
            WHERE award_status = 'submission_open'
              AND source_table LIKE '%223%'
              AND tender_link ILIKE '%notice223%'
          ) AS open_223_public,
          COUNT(*) FILTER (
            WHERE award_status = 'submission_open'
              AND source_table LIKE '%44%'
              AND tender_link ILIKE '%regNumber=%'
          ) AS open_44_public
        FROM crm_procurements
        """
    )[0]

    buckets = crm.execute_query(
        """
        WITH base AS (
          SELECT
            CASE
              WHEN source_table LIKE '%223%' THEN '223'
              WHEN source_table LIKE '%44%' THEN '44'
              ELSE 'OTHER'
            END AS law,
            end_date - CURRENT_DATE AS days
          FROM crm_procurements
          WHERE crm_stage = 'torgi'
            AND award_status = 'submission_open'
            AND end_date >= CURRENT_DATE
        )
        SELECT law,
          COUNT(*) FILTER (WHERE days <= 30) AS within_30,
          COUNT(*) FILTER (WHERE days BETWEEN 31 AND 90) AS d31_90,
          COUNT(*) FILTER (WHERE days BETWEEN 91 AND 180) AS d91_180,
          COUNT(*) FILTER (WHERE days BETWEEN 181 AND 365) AS d181_365,
          COUNT(*) FILTER (WHERE days > 365) AS over_365,
          COUNT(*) AS total
        FROM base
        GROUP BY law
        ORDER BY law
        """
    )

    over365 = crm.execute_query(
        """
        SELECT id, contract_number, end_date, start_date, source_updated_at, tender_link
        FROM crm_procurements
        WHERE crm_stage = 'torgi'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE + INTERVAL '365 days'
        ORDER BY end_date DESC, id
        """
    )

    sample44 = crm.execute_query(
        """
        SELECT id, source_table, contract_number, tender_link, end_date
        FROM crm_procurements
        WHERE source_table LIKE '%44%'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE
          AND tender_link ILIKE '%regNumber=%'
        ORDER BY end_date ASC, id
        LIMIT 10
        """
    )
    sample223 = crm.execute_query(
        """
        SELECT id, source_table, contract_number, tender_link, end_date
        FROM crm_procurements
        WHERE source_table LIKE '%223%'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE
          AND tender_link ILIKE '%notice223%'
        ORDER BY end_date ASC, id
        LIMIT 10
        """
    )

    # identity match checks for samples
    def match_row(r: dict) -> dict:
        v = resolve_procurement_link(
            source_table=r["source_table"],
            contract_number=r["contract_number"],
            tender_link=r["tender_link"],
        )
        return {
            "CRM_ID": r["id"],
            "LAW": "223" if "223" in (r["source_table"] or "") else "44",
            "PROCUREMENT_NUMBER": r["contract_number"],
            "CURRENT_TENDER_LINK": r["tender_link"],
            "RESOLVED_PUBLIC_URL": v.public_url,
            "RENDER_DIRECT": v.render_direct_link,
            "LINK_MATCHES_IDENTITY": bool(
                v.render_direct_link
                and v.public_url
                and r["contract_number"]
                and r["contract_number"] in (v.public_url or "")
            ),
            "DEADLINE": str(r["end_date"]),
            "RESULT": "PASS" if v.render_direct_link else "NO_DIRECT",
        }

    out = {
        "control": control,
        "control_view": {
            "procurement_number": view.procurement_number,
            "public_url": view.public_url,
            "validity": view.validity.value,
            "render_direct_link": view.render_direct_link,
            "notice_info_id": view.notice_info_id,
        },
        "stats": stats,
        "by_stage": by_stage,
        "PRIVATE_LK_WITH_PUBLIC_NUMBER": private_with_num,
        "PRIVATE_LK_WITHOUT_PUBLIC_NUMBER": private_without_num,
        "leftover_sample": leftover_sample,
        "affected_remaining_private": affected,
        "buckets": buckets,
        "over365": over365,
        "parity44": [match_row(r) for r in sample44],
        "parity223": [match_row(r) for r in sample223],
    }
    print(json.dumps(out, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
