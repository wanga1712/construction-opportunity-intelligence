#!/usr/bin/env python3
"""Parse-only identity census for isolated notice/615 XML. No DB."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def strip_ns(text: str) -> str:
    text = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", text)
    text = re.sub(r"<(/?)(\w+):", r"<\1", text)
    return re.sub(r"(\s)(\w+):", r"\1", text)


def first_text(root, *names: str):
    for name in names:
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == name and elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def classify(path: Path) -> str:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if "615" in parts or name.startswith("pprf615"):
        return "615"
    if "223" in parts or "purchasenotice" in name:
        return "223_notice"
    return "44_notice"


def main() -> int:
    root = Path(os.environ.get("PARITY_XML_ROOT", "")).expanduser()
    if not root.is_dir():
        raise SystemExit("set PARITY_XML_ROOT")
    counts = Counter()
    ids = {"44_notice": set(), "223_notice": set(), "615": set()}
    regions = set()
    xml_total = 0
    for path in root.rglob("*.xml"):
        xml_total += 1
        kind = classify(path)
        counts[kind] += 1
        for part in path.parts:
            if part.isdigit() and 1 <= len(part) <= 2:
                regions.add(part.zfill(2))
        try:
            raw = strip_ns(path.read_text(encoding="utf-8"))
            tree = ET.fromstring(raw)
        except Exception:
            counts[kind + "_parse_fail"] += 1
            continue
        if kind == "44_notice":
            ident = first_text(tree, "purchaseNumber", "notificationNumber")
        elif kind == "223_notice":
            ident = first_text(tree, "purchaseNoticeNumber", "registrationNumber")
        else:
            ident = first_text(tree, "notificationNumber", "purchaseNumber", "regNumber")
        if ident:
            ids[kind].add(ident)
        else:
            counts[kind + "_no_id"] += 1
    print("PARITY_TOTAL_XML=" + str(xml_total))
    print("PARITY_44FZ_XML=" + str(counts["44_notice"]))
    print("PARITY_223FZ_XML=" + str(counts["223_notice"]))
    print("PARITY_615_XML=" + str(counts["615"]))
    print("PARITY_REGIONS=" + str(len(regions)))
    print("44_NOTICE_IDENTITIES=" + str(len(ids["44_notice"])))
    print("223_NOTICE_IDENTITIES=" + str(len(ids["223_notice"])))
    print("615_IDENTITIES=" + str(len(ids["615"])))
    print("44_NOTICE_NO_ID=" + str(counts["44_notice_no_id"]))
    print("223_NOTICE_NO_ID=" + str(counts["223_notice_no_id"]))
    print("615_NO_ID=" + str(counts["615_no_id"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
