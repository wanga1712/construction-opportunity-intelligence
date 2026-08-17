#!/usr/bin/env python3
"""Full source chronology for the 8 remaining RGK price mismatches. Read-only."""
from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file
from parsing_xml.xml_parser import XMLParser
from secondary_functions import load_config

OUT = Path("/tmp/eis_s7_correctness")
RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
NUMBERS = [
    "0172200004926000387",
    "0373200315425000007",
    "0373200333526000009",
    "0160300003626000356",
    "0315100000526000418",
    "0351400001326000392",
    "0348100013126000155",
]
NAME_RE = re.compile(
    r"^contract_(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$"
)


def first_text(root, names: list[str]):
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
    reports = []
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '180s'")
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='reestr_contract_44_fz'
            """
        )
        cols_main = {r[0] for r in cur.fetchall()}
        extra = [c for c in ("created_at", "updated_at", "initial_price") if c in cols_main]
        extra_sql = (", " + ", ".join(extra)) if extra else ""
        for number in NUMBERS:
            files = sorted(p.name for p in RGK.glob(f"*{number}*") if p.name.endswith(".xml"))
            xmls = []
            for name in files:
                path = RGK / name
                rec, _ = parse_rgk_file(str(path), tags)
                raw = Path(path).read_text(encoding="utf-8", errors="replace")
                cleaned = XMLParser.remove_namespaces(raw)
                import xml.etree.ElementTree as ET

                root = ET.fromstring(cleaned)
                match = NAME_RE.match(name)
                xmls.append(
                    {
                        "file_name": name,
                        "filename_number": match.group("number") if match else None,
                        "filename_version": int(match.group("ver")) if match else None,
                        "guid": match.group("guid").upper() if match else None,
                        "xml_contract_number": rec.contract_number if rec else None,
                        "parsed_price": rec.final_price if rec else None,
                        "raw_price": first_text(root, ["price", "contractPrice", "priceValue"]),
                        "publish_dt": first_text(
                            root,
                            ["docPublishDate", "publishDate", "hrefLastUpdate", "modificationDate", "signDate"],
                        ),
                        "version_number": first_text(root, ["versionNumber", "docVersion", "editionNumber"]),
                        "delivery_start": rec.delivery_start_date if rec else None,
                        "delivery_end": rec.delivery_end_date if rec else None,
                    }
                )
            cur.execute(
                "SELECT file_name, processed_at FROM file_names_xml WHERE file_name = ANY(%s) ORDER BY processed_at, id",
                (files or ["__none__"],),
            )
            processed = [
                {"file_name": a, "processed_at": b.isoformat() if b else None} for a, b in cur.fetchall()
            ]
            db_rows = []
            for loc, table in (
                ("main", "reestr_contract_44_fz"),
                ("awarded", "reestr_contract_44_fz_awarded"),
                ("commission", "reestr_contract_44_fz_commission_work"),
                ("unclear", "reestr_contract_44_fz_unclear"),
                ("unknown", "reestr_contract_44_fz_unknown"),
            ):
                try:
                    cur.execute(
                        f"SELECT id, contract_number, final_price, contractor_id, okpd_id{extra_sql} FROM {table} WHERE contract_number = %s",
                        (number,),
                    )
                except Exception:
                    conn.rollback()
                    continue
                colnames = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    rec = dict(zip(colnames, row))
                    rec["table"] = loc
                    rec["final_price"] = str(rec["final_price"]) if rec.get("final_price") is not None else None
                    db_rows.append(rec)
            canonical = None
            dated = [x for x in xmls if x.get("filename_version") is not None]
            if dated:
                canonical = sorted(
                    dated,
                    key=lambda x: (
                        x.get("filename_version") or -1,
                        x.get("publish_dt") or "",
                        x.get("guid") or "",
                    ),
                )[-1]
            xml_prices = []
            for item in xmls:
                if item.get("parsed_price"):
                    xml_prices.append(str(Decimal(str(item["parsed_price"]))))
            db_prices = [r["final_price"] for r in db_rows if r.get("final_price")]
            match_any = bool(set(xml_prices) & set(db_prices))
            reports.append(
                {
                    "number": number,
                    "xml_files": xmls,
                    "processed": processed,
                    "db_rows": db_rows,
                    "canonical_source_xml": canonical,
                    "any_xml_price_in_db": match_any,
                }
            )
    (OUT / "phaseE_price_chronology.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({"contracts": len(reports), "files": [len(r["xml_files"]) for r in reports]}, indent=2))


if __name__ == "__main__":
    main()
