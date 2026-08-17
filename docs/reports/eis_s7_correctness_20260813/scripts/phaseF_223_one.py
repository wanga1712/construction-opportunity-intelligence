#!/usr/bin/env python3
from pathlib import Path
import re
import xml.etree.ElementTree as ET

rootdir = Path("/tmp/eis_correctness_20260813/xml/223_NOTICE")
hits = list(rootdir.rglob("*32616267298*.xml"))
print("files", [p.name for p in hits])


def strip(text: str) -> str:
    text = re.sub(r"\sxmlns(:\w+)?=\"[^\"]+\"", "", text)
    text = re.sub(r"<(/?)(\w+):", r"<\1", text)
    text = re.sub(r"(\s)(\w+):", r"\1", text)
    return text


for path in hits:
    root = ET.fromstring(strip(path.read_text(encoding="utf-8", errors="replace")))
    for tag in (
        "submissionCloseDateTime",
        "submissionStartDateTime",
        "purchaseNoticeData/registrationNumber",
    ):
        elem = root.find(".//" + tag)
        value = elem.text.strip() if elem is not None and elem.text else None
        print(path.name, tag, value)
