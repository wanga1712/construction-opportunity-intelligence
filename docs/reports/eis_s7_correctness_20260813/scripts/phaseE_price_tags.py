#!/usr/bin/env python3
"""Dump all price-like XML tags for the two single-file kopeck mismatches."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")
from parsing_xml.xml_parser import XMLParser
import xml.etree.ElementTree as ET

RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
FILES = [
    "contract_1540810013826000368_0_019FF95BBC8572338D8D94AA7831E6E0.xml",
    "contract_1503200412726000146_0_019FF9E0150076C3A1A5E9AD7467C5B2.xml",
]
PRICE_HINTS = ("price", "amount", "sum", "cost", "value")


def main() -> None:
    out = []
    for name in FILES:
        path = RGK / name
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(XMLParser.remove_namespaces(raw))
        tags = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            text = (elem.text or "").strip()
            if not text:
                continue
            low = tag.lower()
            if any(h in low for h in PRICE_HINTS) or (text.replace(".", "", 1).replace("-", "", 1).isdigit() and "." in text):
                if any(h in low for h in PRICE_HINTS):
                    tags.append({"tag": tag, "text": text[:80]})
        out.append({"file": name, "price_tags": tags[:40]})
    Path("/tmp/eis_s7_correctness/phaseE_price_tags.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
