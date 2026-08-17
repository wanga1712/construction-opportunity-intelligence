#!/usr/bin/env python3
"""Classify re-downloaded 2026-08-13 notice XML vs production filter + registry. Read-only DB."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import xml.etree.ElementTree as ET
from database_work.database_connection import DatabaseManager
from parsing_xml.xml_parser import XMLParser

ROOT = Path("/tmp/eis_correctness_20260813")
OUT = Path("/tmp/eis_s7_correctness")
NAME_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+)_(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$"
)
TABLES_44 = [
    "reestr_contract_44_fz",
    "reestr_contract_44_fz_commission_work",
    "reestr_contract_44_fz_unknown",
    "reestr_contract_44_fz_unclear",
    "reestr_contract_44_fz_awarded",
]
TABLES_223 = [
    "reestr_contract_223_fz",
    "reestr_contract_223_fz_commission_work",
    "reestr_contract_223_fz_unclear",
    "reestr_contract_223_fz_awarded",
]


def first_text(root, names: list[str]) -> str | None:
    for name in names:
        for elem in root.findall(f".//{name}"):
            if elem is not None and elem.text and elem.text.strip():
                return elem.text.strip()
    return None


def extract_okpd(root) -> str | None:
    for xpath in (".//OKPDCode", ".//okpd2/code", ".//OKPD2/code"):
        elem = root.find(xpath)
        if elem is not None and elem.text and elem.text.strip():
            code = elem.text.strip()
            if len(code.split(".")) == 2 and code.endswith("0"):
                code = code[:-1]
            return code
    return None


def parse_file(path: Path, contour: str, region: str) -> dict:
    name = path.name
    match = NAME_RE.match(name)
    rec = {
        "file": name,
        "contour": contour,
        "region": region,
        "number": match.group("number") if match else None,
        "version": int(match.group("ver")) if match else None,
        "prefix": match.group("prefix") if match else name.split("_", 1)[0],
        "okpd": None,
        "title": None,
        "parse_error": None,
    }
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(XMLParser.remove_namespaces(raw))
    except Exception as exc:
        rec["parse_error"] = f"{type(exc).__name__}: {exc}"
        return rec
    rec["okpd"] = extract_okpd(root)
    rec["title"] = first_text(
        root,
        ["purchaseObjectInfo", "contractSubject", "purchaseObjectName", "name"],
    )
    xml_number = first_text(
        root,
        ["purchaseNumber", "notificationNumber", "purchaseNoticeNumber", "registrationNumber"],
    )
    if xml_number:
        rec["xml_number"] = xml_number
    return rec


def load_present(cur, tables: list[str], numbers: list[str]) -> set[str]:
    found: set[str] = set()
    if not numbers:
        return found
    for table in tables:
        for i in range(0, len(numbers), 500):
            batch = numbers[i : i + 500]
            try:
                cur.execute(f"SELECT contract_number FROM {table} WHERE contract_number = ANY(%s)", (batch,))
            except Exception:
                continue
            found.update(str(r[0]) for r in cur.fetchall())
    return found


def classify_row(rec: dict, okpd_ok: set[str], present: set[str]) -> str:
    if rec.get("parse_error"):
        return "PARSER_ERROR"
    number = rec.get("number")
    if rec["contour"] in {"44_NOTICE", "223_NOTICE"}:
        if not rec.get("okpd"):
            return "INTENTIONALLY_FILTERED_INVALID"
        if rec["okpd"] not in okpd_ok:
            return "INTENTIONALLY_FILTERED_OKPD"
        if rec["contour"] == "44_NOTICE" and not rec.get("title"):
            return "INTENTIONALLY_FILTERED_EMPTY_TITLE"
        if number and number in present:
            return "PRESENT_IN_REGISTRY"
        if rec.get("xml_number") and rec["xml_number"] in present:
            return "PRESENT_IN_REGISTRY"
        return "MISSING"
    # 615
    if rec["region"] not in {"50", "77"}:
        return "INTENTIONALLY_FILTERED_INVALID"
    if not rec.get("title") and not rec.get("number"):
        return "INTENTIONALLY_FILTERED_INVALID"
    if number and number in present:
        return "PRESENT_IN_REGISTRY"
    return "MISSING"


def main() -> None:
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    files: list[dict] = []
    xml_root = ROOT / "xml"
    for contour in ("44_NOTICE", "223_NOTICE", "615"):
        base = xml_root / contour
        if not base.exists():
            continue
        for region_dir in base.iterdir():
            if not region_dir.is_dir():
                continue
            for path in region_dir.glob("*.xml"):
                files.append(parse_file(path, contour, region_dir.name))

    with conn.cursor() as cur:
        cur.execute("SELECT sub_code FROM collection_codes_okpd")
        okpd_ok = {str(r[0]) for r in cur.fetchall() if r[0]}
        nums_44 = [r["number"] for r in files if r["contour"] == "44_NOTICE" and r.get("number")]
        nums_223 = [r["number"] for r in files if r["contour"] == "223_NOTICE" and r.get("number")]
        nums_615 = [r["number"] for r in files if r["contour"] == "615" and r.get("number")]
        present_44 = load_present(cur, TABLES_44, nums_44)
        present_223 = load_present(cur, TABLES_223, nums_223)
        present_615 = set()
        if nums_615:
            cur.execute(
                "SELECT contract_number FROM reestr_contract_615_pp WHERE contract_number = ANY(%s)",
                (nums_615,),
            )
            present_615 = {str(r[0]) for r in cur.fetchall()}

    by = {"44_NOTICE": Counter(), "223_NOTICE": Counter(), "615": Counter()}
    unique = {"44_NOTICE": {}, "223_NOTICE": {}, "615": {}}
    for rec in files:
        present = present_44 if rec["contour"] == "44_NOTICE" else present_223 if rec["contour"] == "223_NOTICE" else present_615
        label = classify_row(rec, okpd_ok, present)
        rec["class"] = label
        by[rec["contour"]][label] += 1
        key = rec.get("number") or rec["file"]
        unique[rec["contour"]].setdefault(key, label)

    unique_counts = {c: dict(Counter(v.values())) for c, v in unique.items()}
    region32 = [r for r in files if r["region"] == "32" and r["contour"] == "223_NOTICE"]
    summary = {
        "files": {c: sum(v.values()) for c, v in by.items()},
        "file_classes": {c: dict(v) for c, v in by.items()},
        "unique_identities": {c: len(v) for c, v in unique.items()},
        "unique_classes": unique_counts,
        "region32_223_files": len(region32),
        "region32_223_classes": dict(Counter(r["class"] for r in region32)),
        "okpd_allowlist_size": len(okpd_ok),
        "missing_samples": {
            c: [r["file"] for r in files if r["contour"] == c and r["class"] == "MISSING"][:15]
            for c in by
        },
    }
    # Duplicate versions among uniques: files - unique
    for contour in by:
        summary.setdefault("duplicate_version_files", {})[contour] = summary["files"][contour] - summary["unique_identities"][contour]
    (OUT / "phaseBCD_notice_balance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
