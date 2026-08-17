#!/usr/bin/env python3
"""Prefix counts for filtered notices + DB chronology for 8 RGK prices. Read-only."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager

OUT = Path("/tmp/eis_s7_correctness")
NAME_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+)_(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$"
)
NUMBERS = [
    "0172200004926000387",
    "0373200315425000007",
    "0373200333526000009",
    "0160300003626000356",
    "0315100000526000418",
    "0351400001326000392",
    "0348100013126000155",
]
TABLES = [
    ("main", "reestr_contract_44_fz"),
    ("awarded", "reestr_contract_44_fz_awarded"),
    ("commission", "reestr_contract_44_fz_commission_work"),
    ("unknown", "reestr_contract_44_fz_unknown"),
    ("unclear", "reestr_contract_44_fz_unclear"),
]


def main() -> None:
    summary = json.loads((OUT / "phaseBCD_production_path.json").read_text(encoding="utf-8"))
    # Recompute prefixes from xml tree using production classes stored? We don't have per-file dump.
    # Walk xml names only for 223 invalid / 44 empty title via a cheap name count.
    xml_root = Path("/tmp/eis_correctness_20260813/xml")
    prefixes = {"44_NOTICE": Counter(), "223_NOTICE": Counter(), "615": Counter()}
    for contour in prefixes:
        base = xml_root / contour
        if not base.exists():
            continue
        for path in base.rglob("*.xml"):
            match = NAME_RE.match(path.name)
            prefixes[contour][match.group("prefix") if match else path.name.split("_")[0]] += 1

    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    prices = {}
    with conn.cursor() as cur:
        for number in NUMBERS:
            rows = []
            for loc, table in TABLES:
                try:
                    cur.execute(
                        f"""
                        SELECT id, final_price::text, initial_price::text,
                               created_at::text, updated_at::text,
                               delivery_start_date::text, delivery_end_date::text
                        FROM {table}
                        WHERE contract_number = %s
                        ORDER BY id
                        """,
                        (number,),
                    )
                except Exception:
                    continue
                for row in cur.fetchall():
                    rows.append(
                        {
                            "table": loc,
                            "id": row[0],
                            "final_price": row[1],
                            "initial_price": row[2],
                            "created_at": row[3],
                            "updated_at": row[4],
                            "delivery_start_date": row[5],
                            "delivery_end_date": row[6],
                        }
                    )
            prices[number] = rows
        # date match on 1447 window registry hits if file exists
        hits_path = Path("/tmp/eis_s7_correctness/phase4_identities.json")
        date_note = "phase4 file not on this host"
        if hits_path.exists():
            date_note = "present"

    out = {
        "prefix_counts": {k: dict(v) for k, v in prefixes.items()},
        "unique_classes": summary.get("unique_classes"),
        "prices": prices,
        "date_note": date_note,
    }
    (OUT / "phaseE_db_prices.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "prefix_counts": out["prefix_counts"],
        "unique_classes": out["unique_classes"],
        "price_updated_at": {
            n: [{"table": r["table"], "id": r["id"], "final_price": r["final_price"],
                 "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]
            for n, rows in prices.items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
