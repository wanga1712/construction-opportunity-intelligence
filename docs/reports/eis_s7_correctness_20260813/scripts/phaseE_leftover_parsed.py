#!/usr/bin/env python3
"""Parse the 28 leftover XML hits for the 8 price numbers. Read-only."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import xml.etree.ElementTree as ET
from parsing_xml.rgk_record import extract_contract_number
from parsing_xml.xml_parser import XMLParser

OUT = Path("/tmp/eis_s7_correctness")
NUMBERS = {
    "0172200004926000387",
    "0373200315425000007",
    "0373200333526000009",
    "0160300003626000356",
    "0315100000526000418",
    "0351400001326000392",
    "0348100013126000155",
}


def first_text(root, names: list[str]) -> str | None:
    for name in names:
        for elem in root.findall(f".//{name}"):
            if elem is not None and elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def main() -> None:
    paths = (OUT / "phaseE_leftover_paths.txt").read_text(encoding="utf-8").splitlines()
    hits: dict[str, list[dict]] = {n: [] for n in NUMBERS}
    others = []
    for raw_path in paths:
        path = Path(raw_path.strip())
        if not path.exists():
            continue
        try:
            root = ET.fromstring(XMLParser.remove_namespaces(path.read_text(encoding="utf-8", errors="replace")))
        except Exception as exc:
            others.append({"file": path.name, "error": str(exc)})
            continue
        number = extract_contract_number(root)
        rec = {
            "file_name": path.name,
            "xml_contract_number": number,
            "parsed_price": first_text(root, ["priceInfo/price"]),
            "any_price": first_text(root, ["priceInfo/price", "price"]),
            "payment_sum": first_text(root, ["paymentSum"]),
            "publish_dt": first_text(root, ["docPublishDate", "publishDTInEIS", "modificationDate"]),
            "version_number": first_text(root, ["versionNumber"]),
            "mtime": path.stat().st_mtime,
        }
        if number in hits:
            hits[number].append(rec)
        else:
            others.append(rec)
    for number, rows in hits.items():
        rows.sort(key=lambda r: (r.get("publish_dt") or "", r.get("version_number") or "", r["file_name"]))
    out = {"hits": hits, "false_positive": others}
    (OUT / "phaseE_leftover_parsed.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    slim = {
        n: [
            {
                "file_name": r["file_name"],
                "price": r["parsed_price"],
                "publish_dt": r["publish_dt"],
                "version_number": r["version_number"],
            }
            for r in rows
        ]
        for n, rows in hits.items()
    }
    print(json.dumps({"counts": {n: len(v) for n, v in hits.items()}, "hits": slim, "false_positive": len(others)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
