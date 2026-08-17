#!/usr/bin/env python3
"""Reclassify 2026-08-13 notice XML using production xpaths. Read-only DB."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import xml.etree.ElementTree as ET
from database_work.database_connection import DatabaseManager
from parsing_xml.xml_parser import XMLParser
from parsing_xml.okpd_parser import extract_okpd_code

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


def xpath_first(root, xpath: str) -> str | None:
    element = root.find(f".//{xpath}")
    if element is not None and element.text and element.text.strip():
        return element.text.strip()
    return None


def prod_field(root, xpath: str) -> str | None:
    """Match XMLParser._parse_common_contract_data: last colon segment, first text."""
    tag = xpath.split(":")[-1]
    for elem in root.findall(f".//{tag}"):
        if elem is not None and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def trim_okpd(code: str | None) -> str | None:
    if not code:
        return None
    code = code.strip()
    if len(code.split(".")) == 2 and code.endswith("0"):
        code = code[:-1]
    return code


def parse_file(path: Path, contour: str, region: str) -> dict:
    name = path.name
    match = NAME_RE.match(name)
    rec = {
        "file": name,
        "contour": contour,
        "region": region,
        "filename_number": match.group("number") if match else None,
        "version": int(match.group("ver")) if match else None,
        "prefix": match.group("prefix") if match else name.split("_", 1)[0],
        "guid": match.group("guid") if match else None,
        "okpd_raw": None,
        "okpd": None,
        "auction_name": None,
        "contract_number": None,
        "parse_error": None,
    }
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(XMLParser.remove_namespaces(raw))
    except Exception as exc:
        rec["parse_error"] = f"{type(exc).__name__}: {exc}"
        return rec
    rec["okpd_raw"] = extract_okpd_code(root)
    rec["okpd"] = trim_okpd(rec["okpd_raw"])
    if contour == "44_NOTICE":
        rec["auction_name"] = prod_field(root, "purchaseObjectInfo")
        rec["contract_number"] = prod_field(root, "purchaseNumber")
    elif contour == "223_NOTICE":
        rec["auction_name"] = prod_field(root, "purchaseNoticeData/name")
        rec["contract_number"] = prod_field(root, "purchaseNoticeData/registrationNumber")
        rec["purchase_notice_number"] = xpath_first(root, "purchaseNoticeNumber") or xpath_first(
            root, "registrationNumber"
        )
    else:
        rec["auction_name"] = prod_field(root, "purchaseSubjectInfo/name") or prod_field(
            root, "purchaseSubjectInfo/name"
        )
        rec["contract_number"] = prod_field(root, "commonInfo/regNum")
        rec["work_kind_code"] = xpath_first(root, "purchaseSubjectInfo/code")
        rec["hydro_hit"] = any(
            kw in (raw.lower())
            for kw in (
                "гидроизол",
                "гидроизоляция",
                "гидроизоляц",
                "мембран",
                "оклеечн",
                "обмазочн",
                "инъекцион",
                "праймер битум",
            )
        )
    return rec


def load_present(cur, tables: list[str], numbers: list[str]) -> set[str]:
    found: set[str] = set()
    uniq = [n for n in dict.fromkeys(numbers) if n]
    for table in tables:
        for i in range(0, len(uniq), 500):
            batch = uniq[i : i + 500]
            try:
                cur.execute(
                    f"SELECT contract_number FROM {table} WHERE contract_number = ANY(%s)",
                    (batch,),
                )
            except Exception:
                continue
            found.update(str(r[0]) for r in cur.fetchall())
    return found


def classify_row(rec: dict, okpd_ok: set[str], present: set[str], seen_names: set[str]) -> str:
    if rec.get("parse_error"):
        return "PARSER_ERROR"
    number = rec.get("contract_number") or rec.get("filename_number")
    if rec["contour"] == "44_NOTICE":
        if not rec.get("okpd"):
            return "INTENTIONALLY_FILTERED_INVALID"
        if rec["okpd"] not in okpd_ok:
            return "INTENTIONALLY_FILTERED_OKPD"
        if not rec.get("auction_name"):
            return "INTENTIONALLY_FILTERED_EMPTY_TITLE"
        if not rec.get("contract_number"):
            return "INTENTIONALLY_FILTERED_INVALID"
        if number in present:
            return "PRESENT_IN_REGISTRY"
        return "MISSING"
    if rec["contour"] == "223_NOTICE":
        if not rec.get("okpd"):
            return "INTENTIONALLY_FILTERED_INVALID"
        if rec["okpd"] not in okpd_ok:
            return "INTENTIONALLY_FILTERED_OKPD"
        if not rec.get("contract_number"):
            return "INTENTIONALLY_FILTERED_INVALID"
        if rec["contract_number"] in present:
            return "PRESENT_IN_REGISTRY"
        alt = rec.get("purchase_notice_number")
        if alt and alt in present:
            return "PRESENT_IN_REGISTRY"
        return "MISSING"
    if rec["region"] not in {"50", "77"}:
        return "INTENTIONALLY_FILTERED_INVALID"
    if not rec.get("contract_number"):
        return "INTENTIONALLY_FILTERED_INVALID"
    if not rec.get("auction_name"):
        return "INTENTIONALLY_FILTERED_EMPTY_TITLE"
    if rec["contract_number"] in present:
        return "PRESENT_IN_REGISTRY"
    return "MISSING"


def prefer_class(old: str | None, new: str) -> str:
    rank = {
        "PRESENT_IN_REGISTRY": 0,
        "PARSER_ERROR": 1,
        "MISSING": 2,
        "INTENTIONALLY_FILTERED_EMPTY_TITLE": 3,
        "INTENTIONALLY_FILTERED_INVALID": 4,
        "INTENTIONALLY_FILTERED_OKPD": 5,
    }
    if old is None:
        return new
    return old if rank.get(old, 9) <= rank.get(new, 9) else new


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
        for region_dir in sorted(base.iterdir()):
            if not region_dir.is_dir():
                continue
            for path in region_dir.glob("*.xml"):
                files.append(parse_file(path, contour, region_dir.name))

    names = [r["file"] for r in files]
    with conn.cursor() as cur:
        cur.execute("SELECT sub_code FROM collection_codes_okpd")
        okpd_ok = {str(r[0]) for r in cur.fetchall() if r[0]}
        seen_names: set[str] = set()
        for i in range(0, len(names), 500):
            batch = names[i : i + 500]
            cur.execute(
                "SELECT DISTINCT file_name FROM file_names_xml WHERE file_name = ANY(%s)",
                (batch,),
            )
            seen_names.update(str(r[0]) for r in cur.fetchall())
        nums_44 = [r.get("contract_number") or r.get("filename_number") for r in files if r["contour"] == "44_NOTICE"]
        nums_223 = []
        for r in files:
            if r["contour"] != "223_NOTICE":
                continue
            if r.get("contract_number"):
                nums_223.append(r["contract_number"])
            if r.get("purchase_notice_number"):
                nums_223.append(r["purchase_notice_number"])
            if r.get("filename_number"):
                nums_223.append(r["filename_number"])
        nums_615 = [r.get("contract_number") or r.get("filename_number") for r in files if r["contour"] == "615"]
        present_44 = load_present(cur, TABLES_44, nums_44)
        present_223 = load_present(cur, TABLES_223, nums_223)
        present_615: set[str] = set()
        uniq_615 = [n for n in dict.fromkeys(nums_615) if n]
        if uniq_615:
            cur.execute(
                "SELECT contract_number FROM reestr_contract_615_pp WHERE contract_number = ANY(%s)",
                (uniq_615,),
            )
            present_615 = {str(r[0]) for r in cur.fetchall()}

    by = {"44_NOTICE": Counter(), "223_NOTICE": Counter(), "615": Counter()}
    unique: dict[str, dict[str, str]] = {"44_NOTICE": {}, "223_NOTICE": {}, "615": {}}
    prefix_missing = defaultdict(Counter)
    for rec in files:
        present = (
            present_44
            if rec["contour"] == "44_NOTICE"
            else present_223
            if rec["contour"] == "223_NOTICE"
            else present_615
        )
        label = classify_row(rec, okpd_ok, present, seen_names)
        rec["class"] = label
        rec["seen_in_file_names_xml"] = rec["file"] in seen_names
        by[rec["contour"]][label] += 1
        key = rec.get("contract_number") or rec.get("filename_number") or rec["file"]
        unique[rec["contour"]][key] = prefer_class(unique[rec["contour"]].get(key), label)
        if label == "MISSING":
            prefix_missing[rec["contour"]][rec["prefix"]] += 1

    unique_counts = {c: dict(Counter(v.values())) for c, v in unique.items()}
    region32 = [r for r in files if r["region"] == "32" and r["contour"] == "223_NOTICE"]
    missing = [r for r in files if r["class"] == "MISSING"]

    def unexplained(contour: str) -> int:
        return int(unique_counts.get(contour, {}).get("MISSING", 0))

    summary = {
        "files": {c: sum(v.values()) for c, v in by.items()},
        "file_classes": {c: dict(v) for c, v in by.items()},
        "unique_identities": {c: len(v) for c, v in unique.items()},
        "unique_classes": unique_counts,
        "duplicate_version_files": {},
        "region32_223_files": len(region32),
        "region32_223_classes": dict(Counter(r["class"] for r in region32)),
        "region32_prefixes": dict(Counter(r["prefix"] for r in region32)),
        "okpd_allowlist_size": len(okpd_ok),
        "seen_in_file_names_xml": sum(1 for r in files if r["file"] in seen_names),
        "not_seen_in_file_names_xml": sum(1 for r in files if r["file"] not in seen_names),
        "missing_unseen": sum(1 for r in missing if r["file"] not in seen_names),
        "prefix_missing": {c: dict(v) for c, v in prefix_missing.items()},
        "missing_empty_auction_name": sum(1 for r in missing if not r.get("auction_name")),
        "missing_empty_contract_number": sum(1 for r in missing if not r.get("contract_number")),
        "missing_samples": {
            c: [
                {
                    "file": r["file"],
                    "region": r["region"],
                    "prefix": r["prefix"],
                    "okpd": r.get("okpd"),
                    "auction_name": (r.get("auction_name") or "")[:80],
                    "contract_number": r.get("contract_number"),
                    "filename_number": r.get("filename_number"),
                    "seen": r["file"] in seen_names,
                }
                for r in files
                if r["contour"] == c and r["class"] == "MISSING"
            ][:12]
            for c in by
        },
        "unexplained_unique": {
            "44_NOTICE": unexplained("44_NOTICE"),
            "223_NOTICE": unexplained("223_NOTICE"),
            "615": unexplained("615"),
        },
    }
    for contour in by:
        summary["duplicate_version_files"][contour] = (
            summary["files"][contour] - summary["unique_identities"][contour]
        )
    (OUT / "phaseBCD_production_path.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
