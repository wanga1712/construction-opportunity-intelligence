#!/usr/bin/env python3
"""Locate leftover RGK XML whose content/filename matches the 8 price numbers."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file
from parsing_xml.xml_parser import XMLParser
from secondary_functions import load_config

OUT = Path("/tmp/eis_s7_correctness")
RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
WINDOW_START = datetime.fromisoformat("2026-08-17T18:17:38+03:00")
WINDOW_END = datetime.fromisoformat("2026-08-17T19:16:13+03:00")
NUMBERS = [
    "0172200004926000387",
    "0373200315425000007",
    "0373200333526000009",
    "0160300003626000356",
    "0315100000526000418",
    "0351400001326000392",
    "0348100013126000155",
]
NAME_RE = re.compile(r"^contract_(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$")


def first_text(root, names):
    for name in names:
        for elem in root.findall(f".//{name}"):
            if elem is not None and elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def main() -> None:
    cfg = load_config()
    tags = json.loads(Path(cfg.get("tags", "get_tags_44_recouped")).read_text(encoding="utf-8"))
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    wanted = set(NUMBERS)
    hits = {n: [] for n in NUMBERS}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT file_name FROM public.file_names_xml
            WHERE processed_at >= %s AND processed_at <= %s
              AND file_name LIKE 'contract_%%'
            """,
            (WINDOW_START, WINDOW_END),
        )
        window_names = [r[0] for r in cur.fetchall()]
    import xml.etree.ElementTree as ET

    scanned = 0
    for name in window_names:
        if not any(n in name for n in wanted):
            path = RGK / name
            if not path.is_file():
                continue
            # still parse: XML number may differ from filename
        path = RGK / name
        if not path.is_file():
            continue
        scanned += 1
        rec, _ = parse_rgk_file(str(path), tags)
        number = rec.contract_number if rec else None
        if number not in wanted and not any(n in name for n in wanted):
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(XMLParser.remove_namespaces(raw))
        match = NAME_RE.match(name)
        target = number if number in wanted else next((n for n in NUMBERS if n in name), None)
        if not target:
            continue
        hits[target].append(
            {
                "file_name": name,
                "in_window_file_names": True,
                "filename_version": int(match.group("ver")) if match else None,
                "guid": match.group("guid").upper() if match else None,
                "xml_contract_number": number,
                "parsed_price": rec.final_price if rec else None,
                "publish_dt": first_text(root, ["docPublishDate", "publishDate", "modificationDate", "signDate"]),
                "version_number": first_text(root, ["versionNumber", "docVersion", "editionNumber"]),
            }
        )

    # leftover files whose basename contains the number but were not in the window list
    window_set = set(window_names)
    for entry in os.scandir(RGK):
        if not entry.is_file() or not entry.name.endswith(".xml"):
            continue
        matched_nums = [n for n in NUMBERS if n in entry.name]
        if not matched_nums:
            continue
        for n in matched_nums:
            if entry.name in window_set:
                continue
            rec, _ = parse_rgk_file(entry.path, tags)
            match = NAME_RE.match(entry.name)
            hits[n].append(
                {
                    "file_name": entry.name,
                    "in_window_file_names": False,
                    "filename_version": int(match.group("ver")) if match else None,
                    "guid": match.group("guid").upper() if match else None,
                    "xml_contract_number": rec.contract_number if rec else None,
                    "parsed_price": rec.final_price if rec else None,
                }
            )

    with conn.cursor() as cur:
        for number, files in hits.items():
            names = [f["file_name"] for f in files]
            if not names:
                continue
            cur.execute(
                "SELECT file_name, MIN(processed_at) FROM file_names_xml WHERE file_name = ANY(%s) GROUP BY file_name",
                (names,),
            )
            first = {a: b.isoformat() if b else None for a, b in cur.fetchall()}
            for item in files:
                item["first_processed_at"] = first.get(item["file_name"])
            cur.execute(
                """
                SELECT 'main' AS loc, id, final_price::text FROM reestr_contract_44_fz WHERE contract_number=%s
                UNION ALL
                SELECT 'awarded', id, final_price::text FROM reestr_contract_44_fz_awarded WHERE contract_number=%s
                UNION ALL
                SELECT 'commission', id, final_price::text FROM reestr_contract_44_fz_commission_work WHERE contract_number=%s
                """,
                (number, number, number),
            )
            hits[number] = {
                "xmls": files,
                "db": [{"loc": a, "id": b, "final_price": c} for a, b, c in cur.fetchall()],
            }

    payload = {"window_contract_files": len(window_names), "scanned_existing": scanned, "hits": hits}
    (OUT / "phaseE_price_hits.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: len(v["xmls"]) if isinstance(v, dict) else len(v) for k, v in hits.items()}, indent=2))


if __name__ == "__main__":
    main()
