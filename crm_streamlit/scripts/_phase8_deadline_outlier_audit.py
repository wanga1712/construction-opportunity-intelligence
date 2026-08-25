#!/usr/bin/env python3
"""Deadline outlier audit for OPEN actionable workset."""
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


def main() -> int:
    _, tender, crm, _ = connect_databases()
    out = {}
    out["buckets"] = crm.execute_query(
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
            WHEN source_table ILIKE '%%44%%' THEN '44'
            WHEN source_table ILIKE '%%223%%' THEN '223'
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
    out["over_365"] = crm.execute_query(
        """
        SELECT id, source_table, source_id, contract_number, start_date, end_date,
               source_updated_at, left(auction_name, 100) AS title
        FROM crm_procurements
        WHERE crm_stage = 'torgi'
          AND award_status = 'submission_open'
          AND end_date > CURRENT_DATE + 365
        ORDER BY end_date DESC, id DESC
        """
    )
    # Control row vs S7
    control = crm.execute_query(
        """
        SELECT id, source_id, contract_number, start_date, end_date, source_updated_at
        FROM crm_procurements WHERE id = 17758
        """
    )
    out["control_crm"] = control[0] if control else None
    s7 = tender.execute_query(
        "SELECT id, contract_number, start_date, end_date, updated_at FROM reestr_contract_223_fz WHERE id = 151355"
    )
    if s7:
        r = s7[0]
        out["control_s7"] = (
            dict(r)
            if isinstance(r, dict)
            else {
                "id": r[0],
                "contract_number": r[1],
                "start_date": r[2],
                "end_date": r[3],
                "updated_at": r[4],
            }
        )
    out["tag_map_note"] = {
        "current_end_date_xpath": "submissionCloseDateTime",
        "pre_2026_08_16_end_date_xpath": "documentationDelivery/deliveryEndDateTime",
        "control_source_updated_at": (out.get("control_crm") or {}).get("source_updated_at"),
        "hypothesis": (
            "Control row last sourced 2026-07-29, before 2026-08-16 tag fix; "
            "2032 likely from documentationDelivery/deliveryEndDateTime and never reparsed."
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
