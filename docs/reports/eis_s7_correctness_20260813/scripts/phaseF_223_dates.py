#!/usr/bin/env python3
"""223 notice date match for PRESENT identities from side re-download. Read-only."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import xml.etree.ElementTree as ET
from database_work.database_connection import DatabaseManager
from parsing_xml.xml_parser import XMLParser

ROOT = Path("/tmp/eis_correctness_20260813/xml/223_NOTICE")
OUT = Path("/tmp/eis_s7_correctness")
NAME_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+)_(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$"
)
TABLES = [
    "reestr_contract_223_fz",
    "reestr_contract_223_fz_commission_work",
    "reestr_contract_223_fz_unclear",
    "reestr_contract_223_fz_awarded",
]


def text(root, xpath: str) -> str | None:
    el = root.find(f".//{xpath}")
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    return None


def day(root, xpath: str) -> str | None:
    value = text(root, xpath)
    return value[:10] if value else None


def main() -> None:
    files = []
    for path in ROOT.rglob("*.xml"):
        match = NAME_RE.match(path.name)
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(XMLParser.remove_namespaces(raw))
        number = text(root, "purchaseNoticeData/registrationNumber")
        if not number:
            continue
        files.append(
            {
                "file": path.name,
                "number": number,
                "end": day(root, "submissionCloseDateTime"),
                "start": day(root, "submissionStartDateTime"),
                "exec_start": day(root, "startExecutionDate"),
                "exec_end": day(root, "endExecutionDate"),
            }
        )
    numbers = list({r["number"] for r in files})
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    present: dict[str, list] = {}
    with conn.cursor() as cur:
        for table in TABLES:
            for i in range(0, len(numbers), 500):
                batch = numbers[i : i + 500]
                try:
                    cur.execute(
                        f"""
                        SELECT contract_number, start_date::text, end_date::text,
                               delivery_start_date::text, delivery_end_date::text
                        FROM {table} WHERE contract_number = ANY(%s)
                        """,
                        (batch,),
                    )
                except Exception:
                    continue
                for row in cur.fetchall():
                    present.setdefault(str(row[0]), []).append(
                        {
                            "table": table,
                            "start": (row[1] or "")[:10],
                            "end": (row[2] or "")[:10],
                            "delivery_start": (row[3] or "")[:10],
                            "delivery_end": (row[4] or "")[:10],
                        }
                    )
    end_match = end_miss = not_present = 0
    samples = []
    seen = set()
    for rec in files:
        if rec["number"] in seen:
            continue
        seen.add(rec["number"])
        rows = present.get(rec["number"])
        if not rows:
            not_present += 1
            continue
        ends = {r["end"] for r in rows if r["end"]}
        if rec["end"] and rec["end"] not in ends:
            end_miss += 1
            if len(samples) < 8:
                samples.append({"number": rec["number"], "xml_end": rec["end"], "db_end": sorted(ends)})
        else:
            end_match += 1
    out = {
        "xml_with_registrationNumber": len(files),
        "unique": len(seen),
        "present": end_match + end_miss,
        "not_present": not_present,
        "end_match": end_match,
        "end_miss": end_miss,
        "samples": samples,
    }
    (OUT / "phaseF_223_dates.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
