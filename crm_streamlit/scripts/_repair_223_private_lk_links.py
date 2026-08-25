#!/usr/bin/env python3
"""Bounded repair: replace 223 private LK tender_link with public EPZ URL.

Repairs CRM (and optionally S7) rows where:
  tender_link is lk.zakupki.gov.ru private noticeInfoId URL
  AND contract_number (registrationNumber) is present.

Does NOT invent URLs when procurement number is missing.
Does NOT change deadlines / model / publication.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/pythonProject89")
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases
from src.services.procurement_identity import (
    build_public_223_url,
    is_private_lk_url,
    normalize_procurement_number,
)


def repair_crm(crm, *, apply: bool) -> dict:
    rows = crm.execute_query(
        """
        SELECT id, source_table, contract_number, tender_link, crm_stage, award_status
        FROM crm_procurements
        WHERE source_table ILIKE %s
          AND tender_link ILIKE %s
        """,
        ("%223%", "%lk.zakupki.gov.ru%"),
    )
    planned = []
    for r in rows:
        number = normalize_procurement_number(r.get("contract_number"))
        if not number or not is_private_lk_url(r.get("tender_link")):
            continue
        public = build_public_223_url(number)
        planned.append(
            {
                "id": r["id"],
                "contract_number": number,
                "old": r["tender_link"],
                "new": public,
                "crm_stage": r.get("crm_stage"),
            }
        )
    updated = 0
    if apply and planned:
        # Deterministic set-based repair from registrationNumber identity.
        updated = crm.execute_update(
            """
            UPDATE crm_procurements
            SET tender_link = 'https://zakupki.gov.ru/epz/order/notice/notice223/common-info.html?regNumber='
                              || btrim(contract_number),
                crm_updated_at = NOW()
            WHERE source_table ILIKE %s
              AND tender_link ILIKE %s
              AND NULLIF(btrim(contract_number), '') IS NOT NULL
              AND btrim(contract_number) NOT ILIKE 'MISSING-%%'
            """,
            ("%223%", "%lk.zakupki.gov.ru%"),
        )
    return {
        "matched_private_lk": len(rows),
        "repairable": len(planned),
        "applied": bool(apply),
        "updated_rows": updated,
        "sample": planned[:10],
        "control_17758_planned": next(
            (p for p in planned if p["id"] == 17758), None
        ),
    }


def repair_s7(tender, *, apply: bool) -> dict:
    rows = tender.execute_query(
        """
        SELECT id, contract_number, tender_link
        FROM reestr_contract_223_fz
        WHERE tender_link ILIKE %s
        """,
        ("%lk.zakupki.gov.ru%",),
    )
    # tender.execute_query may return dicts or tuples
    planned = []
    for r in rows:
        if isinstance(r, dict):
            rid, cn, link = r.get("id"), r.get("contract_number"), r.get("tender_link")
        else:
            rid, cn, link = r[0], r[1], r[2]
        number = normalize_procurement_number(cn)
        if not number or not is_private_lk_url(link):
            continue
        planned.append({"id": rid, "contract_number": number, "new": build_public_223_url(number)})
    if apply and planned:
        for item in planned:
            tender.execute_query(
                """
                UPDATE reestr_contract_223_fz
                SET tender_link = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (item["new"], item["id"]),
            )
    return {"matched_private_lk": len(rows), "repairable": len(planned), "applied": bool(apply), "sample": planned[:10]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--s7", action="store_true", help="also repair S7 reestr_contract_223_fz")
    args = parser.parse_args()
    _, tender, crm, warn = connect_databases()
    out = {"db_warn": warn, "crm": repair_crm(crm, apply=args.apply)}
    if args.s7:
        out["s7"] = repair_s7(tender, apply=args.apply)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
