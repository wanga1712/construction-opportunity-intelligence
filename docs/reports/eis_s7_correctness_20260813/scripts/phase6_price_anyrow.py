#!/usr/bin/env python3
"""Re-check RGK prices against ANY registry row, not the first UNION hit."""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")
from database_work.database_connection import DatabaseManager

OUT = Path("/tmp/eis_s7_correctness")
samples = json.loads((OUT / "phase4_identities.json").read_text(encoding="utf-8"))[
    "rgk_mismatch_samples"
]["PRICE"]


def main() -> None:
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    results = []
    with conn.cursor() as cur:
        for item in samples:
            number = item["number"]
            xml_price = Decimal(item["xml"])
            cur.execute(
                """
                SELECT loc, id, final_price FROM (
                  SELECT 'main' AS loc, id, final_price FROM reestr_contract_44_fz WHERE contract_number = %s
                  UNION ALL
                  SELECT 'awarded', id, final_price FROM reestr_contract_44_fz_awarded WHERE contract_number = %s
                  UNION ALL
                  SELECT 'commission', id, final_price FROM reestr_contract_44_fz_commission_work WHERE contract_number = %s
                  UNION ALL
                  SELECT 'unclear', id, final_price FROM reestr_contract_44_fz_unclear WHERE contract_number = %s
                ) s
                """,
                (number, number, number, number),
            )
            rows = [{"loc": a, "id": b, "final_price": str(c) if c is not None else None} for a, b, c in cur.fetchall()]
            matched = [
                r for r in rows
                if r["final_price"] is not None and Decimal(r["final_price"]) == xml_price
            ]
            results.append(
                {
                    "number": number,
                    "xml": item["xml"],
                    "row_count": len(rows),
                    "any_row_matches_xml": bool(matched),
                    "matched": matched[:5],
                    "distinct_db_prices": sorted({r["final_price"] for r in rows}),
                }
            )
    summary = {
        "samples": len(results),
        "any_row_match": sum(1 for r in results if r["any_row_matches_xml"]),
        "still_mismatch": sum(1 for r in results if not r["any_row_matches_xml"]),
        "rows": results,
    }
    (OUT / "phase6_price_anyrow.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
