#!/usr/bin/env python3
"""Dump region-32 forensic jobs and sample filtered notice XML. No DB writes."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import xml.etree.ElementTree as ET

ROOT = Path("/tmp/eis_correctness_20260813")
OUT = Path("/tmp/eis_s7_correctness")


def remove_ns(xml_string: str) -> str:
    import re
    no = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", xml_string)
    no = re.sub(r"<(/?)(\w+):", r"<\1", no)
    no = re.sub(r"(\s)(\w+):", r"\1", no)
    return no


def first(root, xpath: str) -> str | None:
    el = root.find(f".//{xpath}")
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    return None


def tags_of(path: Path, limit=40) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(remove_ns(raw))
    tags = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def main() -> None:
    jobs = []
    for line in (ROOT / "progress.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        region = str(rec.get("region") or rec.get("region_code") or "")
        if region == "32" or rec.get("path", "").find("/32/") >= 0:
            jobs.append(rec)
    r32 = {
        "jobs": len(jobs),
        "by_type": dict(Counter(str(j.get("doc_type") or j.get("type") or j.get("documentType") or j)[:80] for j in jobs[:200])),
        "raw_keys": sorted({k for j in jobs for k in j.keys()}) if jobs else [],
        "sample": jobs[:8],
        "oa": [j for j in jobs if "OA" in json.dumps(j, ensure_ascii=False)],
    }
    # 44 empty-title sample
    ezt = next(Path("/tmp/eis_correctness_20260813/xml/44_NOTICE").rglob("epNotificationEZT2020_0810500001826000017_*.xml"), None)
    aes = next(Path("/tmp/eis_correctness_20260813/xml/223_NOTICE").rglob("purchaseNoticeAESMBO_32616289983_*.xml"), None)
    p615 = next(Path("/tmp/eis_correctness_20260813/xml/615").rglob("pprf615ContractProcedure_262770109055900178_*.xml"), None)
    samples = {}
    for key, path in (("ezt", ezt), ("aesmbo", aes), ("pp615", p615)):
        if not path:
            samples[key] = None
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(remove_ns(raw))
        samples[key] = {
            "file": path.name,
            "purchaseObjectInfo": first(root, "purchaseObjectInfo"),
            "purchaseNumber": first(root, "purchaseNumber"),
            "purchaseObjectName": first(root, "purchaseObjectName"),
            "name": first(root, "name"),
            "registrationNumber": first(root, "registrationNumber"),
            "purchaseNoticeData_name": first(root, "purchaseNoticeData/name"),
            "purchaseNoticeData_reg": first(root, "purchaseNoticeData/registrationNumber"),
            "purchaseNoticeNumber": first(root, "purchaseNoticeNumber"),
            "regNum": first(root, "commonInfo/regNum"),
            "work_kind_name": first(root, "purchaseSubjectInfo/name"),
            "work_kind_code": first(root, "purchaseSubjectInfo/code"),
            "tags": tags_of(path),
        }
    out = {"region32_jobs": r32, "samples": samples}
    (OUT / "phaseBCD_filter_samples.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2)[:8000])


if __name__ == "__main__":
    main()
