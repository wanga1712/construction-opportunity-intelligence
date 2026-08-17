#!/usr/bin/env python3
"""Explain 2 RGK start-date misses. Read-only."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import xml.etree.ElementTree as ET
from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file
from parsing_xml.xml_parser import XMLParser
from secondary_functions import load_config

NUMBERS = ["0373200333526000009", "0813500000122020516"]
RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
OUT = Path("/tmp/eis_s7_correctness")


def main() -> None:
    tags = json.loads(Path(load_config().get("tags", "get_tags_44_recouped")).read_text(encoding="utf-8"))
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    hits = {n: [] for n in NUMBERS}
    paths = (OUT / "phaseF_date_paths.txt").read_text(encoding="utf-8").splitlines()
    for raw_path in paths:
        path = Path(raw_path.strip())
        if not path.is_file():
            continue
        rec, _ = parse_rgk_file(str(path), tags)
        if rec and rec.contract_number in hits:
            raw = path.read_text(encoding="utf-8", errors="replace")
            root = ET.fromstring(XMLParser.remove_namespaces(raw))
            starts = [e.text.strip() for e in root.findall(".//executionPeriod/startDate") if e.text]
            ends = [e.text.strip() for e in root.findall(".//executionPeriod/endDate") if e.text]
            hits[rec.contract_number].append(
                {
                    "file": path.name,
                    "start": rec.delivery_start_date,
                    "end": rec.delivery_end_date,
                    "all_starts": starts,
                    "all_ends": ends[:4],
                    "price": rec.final_price,
                }
            )
    with conn.cursor() as cur:
        for n, files in hits.items():
            cur.execute(
                """
                SELECT 'awarded', id, delivery_start_date::text, delivery_end_date::text,
                       final_price::text, created_at::text, updated_at::text
                FROM reestr_contract_44_fz_awarded WHERE contract_number=%s
                UNION ALL
                SELECT 'main', id, delivery_start_date::text, delivery_end_date::text,
                       final_price::text, created_at::text, updated_at::text
                FROM reestr_contract_44_fz WHERE contract_number=%s
                """,
                (n, n),
            )
            hits[n] = {"xmls": files, "db": [
                {"table": a, "id": b, "start": c, "end": d, "price": e, "created": f, "updated": g}
                for a, b, c, d, e, f, g in cur.fetchall()
            ]}
    (OUT / "phaseF_date_misses.json").write_text(json.dumps(hits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({n: {"xmls": len(v["xmls"]), "db": v["db"], "xml_starts": [x["start"] for x in v["xmls"]], "files": [x["file"] for x in v["xmls"]]} for n, v in hits.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
