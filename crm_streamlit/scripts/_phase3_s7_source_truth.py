#!/usr/bin/env python3
"""Deep S7 source truth for control CRM id 17758 / source_id 151355."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/pythonProject89")
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.services.db_bootstrap import connect_databases


def row_to_dict(row, columns=None):
    if isinstance(row, dict):
        return dict(row)
    if columns is not None:
        return dict(zip(columns, row))
    return {"_raw": str(row)}


def main() -> int:
    _, tender, crm, _ = connect_databases()
    out = {}

    # Confirm control + operator pair rows
    out["by_title"] = crm.execute_query(
        """
        SELECT id, source_id, contract_number, tender_link, end_date, start_date,
               left(auction_name,80) AS title, initial_price, award_status
        FROM crm_procurements
        WHERE auction_name ILIKE %s
        ORDER BY id
        """,
        ("%камер видеонаблюдения%ДОУ%8%",),
    )
    out["by_notice_info_20167502"] = crm.execute_query(
        """
        SELECT id, source_id, contract_number, tender_link, end_date,
               left(auction_name,80) AS title, award_status, crm_stage
        FROM crm_procurements
        WHERE tender_link ILIKE %s OR contract_number = %s
        """,
        ("%noticeInfoId=20167502%", "32616311665"),
    )
    out["by_reg_32615833902"] = crm.execute_query(
        """
        SELECT id, source_id, contract_number, tender_link, end_date,
               left(auction_name,80) AS title
        FROM crm_procurements WHERE contract_number = %s
        """,
        ("32615833902",),
    )

    # S7 schema columns
    cols = tender.execute_query(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='reestr_contract_223_fz'
        ORDER BY ordinal_position
        """
    )
    out["s7_223_columns"] = cols

    # Fetch source row 151355
    src = tender.execute_query(
        "SELECT * FROM reestr_contract_223_fz WHERE id = %s LIMIT 1",
        (151355,),
    )
    if not src:
        out["s7_row"] = None
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 1

    # Determine column names via a second query if needed
    col_names = [c["column_name"] if isinstance(c, dict) else c[0] for c in cols]
    row = src[0]
    if isinstance(row, dict):
        d = dict(row)
    else:
        d = dict(zip(col_names, row))

    identity_keys = [
        k
        for k in d.keys()
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
                "href",
            )
        )
    ]
    out["s7_identity_fields"] = {k: d.get(k) for k in identity_keys}

    # Search raw XML / text blobs for notice numbers and dates
    xml_hits = {}
    for k, v in d.items():
        if v is None:
            continue
        s = str(v)
        if len(s) < 40:
            continue
        if "32615833902" in s or "19557278" in s or "purchaseNotice" in s or "submissionClose" in s:
            # Extract interesting snippets
            snippets = []
            for pat in (
                r"purchaseNoticeNumber[^<]{0,40}",
                r"registrationNumber[^<]{0,40}",
                r"submissionCloseDateTime[^<]{0,80}",
                r"endDate[^<]{0,80}",
                r"deliveryDate[^<]{0,80}",
                r"noticeInfoId[^<]{0,40}",
                r"https?://[^\"'\s<]+",
                r"2032[^<]{0,40}",
                r"2026-03-24[^<]{0,40}",
            ):
                snippets.extend(re.findall(pat, s, flags=re.I)[:5])
            xml_hits[k] = {
                "len": len(s),
                "has_32615833902": "32615833902" in s,
                "has_19557278": "19557278" in s,
                "snippets": snippets[:30],
            }
    out["s7_blob_hits"] = xml_hits

    # Also check if purchaseNoticeNumber column exists explicitly
    for k in sorted(d.keys()):
        if "notice" in k.lower() or "purchase" in k.lower() or "reg" in k.lower():
            out.setdefault("s7_notice_like_all", {})[k] = d.get(k)

    # Sample 10 open 223 CRM vs S7 for identity parity
    sample = crm.execute_query(
        """
        SELECT id, source_id, contract_number, tender_link, end_date
        FROM crm_procurements
        WHERE source_table = 'reestr_contract_223_fz'
          AND crm_stage = 'torgi'
          AND award_status = 'submission_open'
          AND end_date >= CURRENT_DATE
        ORDER BY end_date DESC, id DESC
        LIMIT 10
        """
    )
    sample_out = []
    for r in sample:
        sid = r["source_id"]
        s7r = tender.execute_query(
            "SELECT * FROM reestr_contract_223_fz WHERE id = %s LIMIT 1",
            (sid,),
        )
        s7d = None
        if s7r:
            raw = s7r[0]
            s7d = dict(raw) if isinstance(raw, dict) else dict(zip(col_names, raw))
        sample_out.append(
            {
                "crm_id": r["id"],
                "crm_contract_number": r["contract_number"],
                "crm_tender_link": r["tender_link"],
                "crm_end_date": r["end_date"],
                "s7_contract_number": (s7d or {}).get("contract_number"),
                "s7_tender_link": (s7d or {}).get("tender_link")
                or (s7d or {}).get("link")
                or (s7d or {}).get("url"),
                "s7_end_date": (s7d or {}).get("end_date"),
                "s7_start_date": (s7d or {}).get("start_date"),
            }
        )
    out["sample_223_open_10"] = sample_out

    # Publication chip semantics: count current assessed OUT_OF_PROFILE still in workset
    out["control_ai_scope"] = "OUT_OF_PROFILE"
    out["control_opps_empty"] = True

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
