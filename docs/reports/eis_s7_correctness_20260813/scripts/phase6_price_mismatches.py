#!/usr/bin/env python3
"""Inspect 44-FZ RGK price mismatches for 2026-08-13 window files."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file
from secondary_functions import load_config

OUT = Path("/tmp/eis_s7_correctness")
RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
NUMBERS = json.loads((OUT / "phase4_identities.json").read_text(encoding="utf-8"))[
    "rgk_mismatch_samples"
]["PRICE"]
NUMBERS = list(dict.fromkeys(item["number"] for item in NUMBERS))


def tags():
    cfg = load_config()
    path = cfg.get("tags", "get_tags_44_recouped")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    t = tags()
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    rows = []
    with conn.cursor() as cur:
        for number in NUMBERS:
            files = sorted(p.name for p in RGK.glob(f"contract_{number}_*.xml"))
            xmls = []
            for name in files:
                rec, _ = parse_rgk_file(str(RGK / name), t)
                xmls.append(
                    {
                        "file": name,
                        "price": rec.final_price if rec else None,
                        "okpd_id": rec.okpd_id if rec else None,
                        "contractor_id": rec.contractor_id if rec else None,
                    }
                )
            cur.execute(
                """
                SELECT 'main' AS loc, id, final_price, contractor_id, okpd_id
                FROM reestr_contract_44_fz WHERE contract_number = %s
                UNION ALL
                SELECT 'awarded', id, final_price, contractor_id, okpd_id
                FROM reestr_contract_44_fz_awarded WHERE contract_number = %s
                UNION ALL
                SELECT 'commission', id, final_price, contractor_id, okpd_id
                FROM reestr_contract_44_fz_commission_work WHERE contract_number = %s
                """,
                (number, number, number),
            )
            db_rows = [
                {"loc": a, "id": b, "final_price": str(c) if c is not None else None,
                 "contractor_id": d, "okpd_id": e}
                for a, b, c, d, e in cur.fetchall()
            ]
            cur.execute(
                """
                SELECT file_name, processed_at
                FROM file_names_xml WHERE file_name = ANY(%s)
                ORDER BY processed_at
                """,
                (files,),
            )
            processed = [{"file": a, "processed_at": b.isoformat() if b else None} for a, b in cur.fetchall()]
            rows.append({"number": number, "xmls": xmls, "db": db_rows, "processed": processed})
    (OUT / "phase6_price_mismatches.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
