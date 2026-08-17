#!/usr/bin/env python3
"""Explain remaining 8 RGK price mismatches from leftover XML + DB. Read-only."""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import xml.etree.ElementTree as ET
from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import extract_contract_number
from parsing_xml.xml_parser import XMLParser

OUT = Path("/tmp/eis_s7_correctness")
LEFTOVER = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
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


def first_text(root, names: list[str]) -> str | None:
    for name in names:
        for elem in root.findall(f".//{name}"):
            if elem is not None and elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def parse_xml(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(XMLParser.remove_namespaces(raw))
    except Exception as exc:
        return {"file_name": path.name, "error": f"{type(exc).__name__}: {exc}"}
    number = extract_contract_number(root)
    if number not in NUMBERS:
        return None
    parts = path.name.split("_")
    return {
        "file_name": path.name,
        "xml_contract_number": number,
        "filename_id": parts[1] if len(parts) > 1 else None,
        "filename_version": parts[2] if len(parts) > 2 else None,
        "guid": parts[3].split(".")[0] if len(parts) > 3 else None,
        "parsed_price": first_text(root, ["priceInfo/price", "price"]),
        "payment_sum": first_text(root, ["paymentSum"]),
        "publish_dt": first_text(root, ["docPublishDate", "publishDTInEIS", "modificationDate"]),
        "version_number": first_text(root, ["versionNumber"]),
        "mtime": path.stat().st_mtime,
    }


def main() -> None:
    hits: dict[str, list[dict]] = {n: [] for n in NUMBERS}
    scanned = 0
    for path in LEFTOVER.glob("contract_*.xml"):
        scanned += 1
        rec = parse_xml(path)
        if rec and rec.get("xml_contract_number") in hits:
            hits[rec["xml_contract_number"]].append(rec)

    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    db_rows: dict[str, list[dict]] = {n: [] for n in NUMBERS}
    file_rows: dict[str, list[dict]] = {n: [] for n in NUMBERS}
    with conn.cursor() as cur:
        for number in NUMBERS:
            for loc, table in TABLES:
                try:
                    cur.execute(
                        f"""
                        SELECT id, contract_number, initial_price::text, final_price::text,
                               created_at::text, updated_at::text
                        FROM {table}
                        WHERE contract_number = %s
                        ORDER BY id
                        """,
                        (number,),
                    )
                except Exception:
                    continue
                for row in cur.fetchall():
                    db_rows[number].append(
                        {
                            "table": loc,
                            "id": row[0],
                            "contract_number": row[1],
                            "initial_price": row[2],
                            "final_price": row[3],
                            "created_at": row[4],
                            "updated_at": row[5],
                        }
                    )
            names = [r["file_name"] for r in hits[number]]
            if names:
                cur.execute(
                    """
                    SELECT file_name, min(processed_at)::text, max(processed_at)::text, count(*)
                    FROM file_names_xml
                    WHERE file_name = ANY(%s)
                    GROUP BY file_name
                    """,
                    (names,),
                )
                by_name = {r[0]: r for r in cur.fetchall()}
                for rec in hits[number]:
                    row = by_name.get(rec["file_name"])
                    rec["processed_at_min"] = row[1] if row else None
                    rec["processed_at_max"] = row[2] if row else None
                    rec["file_names_rows"] = int(row[3]) if row else 0

    classified = {}
    for number in NUMBERS:
        xmls = sorted(
            hits[number],
            key=lambda r: (r.get("publish_dt") or "", r.get("version_number") or "", r["file_name"]),
        )
        latest = xmls[-1] if xmls else None
        db = db_rows[number]
        live_prices = {r["final_price"] for r in db if r.get("final_price") is not None}
        latest_price = latest["parsed_price"] if latest else None
        match_latest = latest_price in live_prices if latest_price else False
        classified[number] = {
            "xml_count": len(xmls),
            "latest_publish": latest.get("publish_dt") if latest else None,
            "latest_file": latest.get("file_name") if latest else None,
            "latest_price": latest_price,
            "db_prices": sorted(live_prices),
            "latest_matches_any_db": match_latest,
            "xmls": xmls,
            "db": db,
        }

    out = {"leftover_scanned": scanned, "numbers": classified}
    (OUT / "phaseE_price_explain.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in {"xmls", "db"}} | {
        "xml_count": v["xml_count"],
        "db_row_count": len(v["db"]),
        "latest_file": v["latest_file"],
        "latest_price": v["latest_price"],
        "db_prices": v["db_prices"],
        "latest_matches_any_db": v["latest_matches_any_db"],
    } for k, v in classified.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
