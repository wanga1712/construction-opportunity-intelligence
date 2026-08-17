#!/usr/bin/env python3
"""Isolated replay: set 0315100000526000418 to canonical leftover price. One contract."""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file
from secondary_functions import load_config

OUT = Path("/tmp/eis_s7_correctness")
NUMBER = "0315100000526000418"
PATHS_FILE = OUT / "phaseE_leftover_paths.txt"


def filename_key(file_name: str) -> tuple:
    parts = Path(file_name).name.split("_")
    version = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 0
    guid = parts[3].split(".")[0].upper() if len(parts) >= 4 else ""
    return (version, guid)


def main() -> None:
    tags = json.loads(Path(load_config().get("tags", "get_tags_44_recouped")).read_text(encoding="utf-8"))
    records = []
    for raw in PATHS_FILE.read_text(encoding="utf-8").splitlines():
        path = Path(raw.strip())
        if not path.is_file():
            continue
        record, _ = parse_rgk_file(str(path), tags)
        if record and record.contract_number == NUMBER:
            records.append(record)
    if not records:
        raise SystemExit("no xml")
    records.sort(key=lambda rec: filename_key(rec.file_name))
    chosen = records[-1]
    canonical_price = Decimal(str(chosen.final_price).strip())
    db = DatabaseManager()
    conn = db.connection
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 'awarded', id, final_price::text, updated_at::text
            FROM reestr_contract_44_fz_awarded WHERE contract_number = %s
            UNION ALL
            SELECT 'main', id, final_price::text, updated_at::text
            FROM reestr_contract_44_fz WHERE contract_number = %s
            """,
            (NUMBER, NUMBER),
        )
        before = [
            {"table": a, "id": b, "final_price": c, "updated_at": d} for a, b, c, d in cur.fetchall()
        ]
        updated = 0
        for row in before:
            if Decimal(str(row["final_price"])) == canonical_price:
                continue
            table = (
                "reestr_contract_44_fz_awarded" if row["table"] == "awarded" else "reestr_contract_44_fz"
            )
            cur.execute(
                f"UPDATE {table} SET final_price = %s WHERE id = %s AND contract_number = %s",
                (canonical_price, row["id"], NUMBER),
            )
            updated += cur.rowcount
    conn.commit()
    out = {
        "number": NUMBER,
        "xml_count": len(records),
        "chosen_file": chosen.file_name,
        "chosen_price": str(canonical_price),
        "filename_key": list(filename_key(chosen.file_name)),
        "before": before,
        "rows_updated": updated,
    }
    (OUT / "phaseE_replay_c.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
