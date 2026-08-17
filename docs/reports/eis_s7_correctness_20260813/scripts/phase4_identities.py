#!/usr/bin/env python3
"""Phase 4-6: classify 2026-08-13 window filenames, parse new 44 RGK XML, match DB."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file

OUT = Path("/tmp/eis_s7_correctness")
RGK_DIR = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
WINDOW_START = datetime.fromisoformat("2026-08-17T18:17:38+03:00")
WINDOW_END = datetime.fromisoformat("2026-08-17T19:16:13+03:00")
NAME_RE = re.compile(r"^(?P<prefix>[A-Za-z0-9]+)_+(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$")

TABLES_44 = [
    "reestr_contract_44_fz",
    "reestr_contract_44_fz_commission_work",
    "reestr_contract_44_fz_unknown",
    "reestr_contract_44_fz_unclear",
    "reestr_contract_44_fz_awarded",
    "reestr_contract_44_fz_completed",
]
TABLES_223 = [
    "reestr_contract_223_fz",
    "reestr_contract_223_fz_commission_work",
    "reestr_contract_223_fz_unclear",
    "reestr_contract_223_fz_awarded",
    "reestr_contract_223_fz_completed",
]
NOTICE_PREFIXES_44 = {
    "epNotificationEF2020",
    "epNotificationEZK2020",
    "epNotificationEOK2020",
    "epNotificationEOKD2020",
    "epNotificationEOT2020",
    "epNotificationEZT2020",
    "epNotificationEF",
    "fcsNotificationEF",
    "fcsNotificationEP",
    "fcsNotificationOK",
    "fcsNotificationZK",
    "fcsNotificationZP",
    "epNotificationCancel",
}
NOTICE_PREFIXES_223 = {
    "purchaseNotice",
    "purchaseNoticeOK",
    "purchaseNoticeOA",
    "purchaseNoticeAE",
    "purchaseNoticeAESMBO",
    "purchaseNoticeZPESMBO",
    "purchaseNoticeKESMBO",
    "purchaseNoticeEP",
    "purchaseNoticeIS",
}
RGK_PREFIXES_44 = {"contract"}
RGK_PREFIXES_223 = {"contractCutted", "contract223"}
PP615_PREFIXES = {"contractPPRF615", "notificationPPRF615", "pprf615"}


def classify(name: str) -> dict:
    match = NAME_RE.match(name or "")
    prefix = (name or "").split("_", 1)[0]
    number = match.group("number") if match else None
    guid = match.group("guid").upper() if match else None
    if prefix in RGK_PREFIXES_44 or prefix.startswith("contract") and prefix not in RGK_PREFIXES_223 and prefix not in PP615_PREFIXES:
        if prefix == "contract":
            contour = "44_RGK"
        elif prefix in RGK_PREFIXES_223 or prefix.startswith("contractCutted"):
            contour = "223_RGK"
        elif "615" in prefix.lower():
            contour = "615"
        else:
            contour = "OTHER"
    elif prefix in NOTICE_PREFIXES_44 or prefix.startswith("epNotification") or prefix.startswith("fcsNotification"):
        contour = "44_NOTICE"
    elif prefix in NOTICE_PREFIXES_223 or prefix.startswith("purchaseNotice"):
        contour = "223_NOTICE"
    elif "615" in prefix.lower() or prefix.startswith("pprf"):
        contour = "615"
    else:
        contour = "OTHER"
    if prefix.startswith("contractCutted"):
        contour = "223_RGK"
    return {
        "file_name": name,
        "prefix": prefix,
        "number": number,
        "guid": guid,
        "contour": contour,
        "parsed": bool(match),
    }


def _num(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def load_tags() -> dict:
    import json as jsonlib
    from secondary_functions import load_config

    config = load_config()
    path = config.get("tags", "get_tags_44_recouped")
    with open(path, "r", encoding="utf-8") as handle:
        return jsonlib.load(handle)


def chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def lookup_numbers(cur, tables, numbers):
    found = {}
    for table in tables:
        for batch in chunks(numbers, 500):
            cur.execute(
                f"SELECT contract_number, id FROM {table} WHERE contract_number = ANY(%s)",
                (batch,),
            )
            for number, rec_id in cur.fetchall():
                found.setdefault(str(number), []).append({"id": rec_id, "table": table})
    return found


def lookup_44_values(cur, numbers):
    values = {}
    sql = """
    SELECT contract_number, final_price, contractor_id, okpd_id,
           delivery_start_date, delivery_end_date, auction_name, 'reestr_contract_44_fz'::text AS table
    FROM reestr_contract_44_fz WHERE contract_number = ANY(%s)
    UNION ALL
    SELECT contract_number, final_price, contractor_id, okpd_id,
           delivery_start_date, delivery_end_date, auction_name, 'reestr_contract_44_fz_awarded'
    FROM reestr_contract_44_fz_awarded WHERE contract_number = ANY(%s)
    UNION ALL
    SELECT contract_number, final_price, contractor_id, okpd_id,
           delivery_start_date, delivery_end_date, auction_name, 'reestr_contract_44_fz_commission_work'
    FROM reestr_contract_44_fz_commission_work WHERE contract_number = ANY(%s)
    """
    for batch in chunks(numbers, 400):
        cur.execute(sql, (batch, batch, batch))
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            values.setdefault(str(rec["contract_number"]), []).append(rec)
    return values


def main() -> None:
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    tags = load_tags()
    out: dict = {}
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
        cur.execute(
            """
            SELECT file_name FROM public.file_names_xml
            WHERE processed_at >= %s AND processed_at <= %s
            """,
            (WINDOW_START, WINDOW_END),
        )
        names = [r[0] for r in cur.fetchall()]
        classified = [classify(n) for n in names]
        by_contour = Counter(x["contour"] for x in classified)
        by_prefix = Counter(x["prefix"] for x in classified)
        unparsed = [x["file_name"] for x in classified if not x["parsed"]]
        out["window_files"] = len(names)
        out["by_contour"] = dict(by_contour)
        out["by_prefix"] = dict(by_prefix.most_common(40))
        out["unparsed_count"] = len(unparsed)
        out["unparsed_sample"] = unparsed[:20]

        ids_44_notice = {x["number"] for x in classified if x["contour"] == "44_NOTICE" and x["number"]}
        ids_44_rgk = {x["number"] for x in classified if x["contour"] == "44_RGK" and x["number"]}
        ids_223_notice = {x["number"] for x in classified if x["contour"] == "223_NOTICE" and x["number"]}
        ids_223_rgk = {x["number"] for x in classified if x["contour"] == "223_RGK" and x["number"]}
        ids_615 = {x["number"] for x in classified if x["contour"] == "615" and x["number"]}
        out["raw_from_filenames"] = {
            "UNIQUE_NOTICE_NUMBERS_44": len(ids_44_notice),
            "UNIQUE_RGK_CONTRACT_NUMBERS_44": len(ids_44_rgk),
            "UNIQUE_PURCHASE_NOTICE_NUMBERS_223": len(ids_223_notice),
            "UNIQUE_RGK_OR_CUTTED_223": len(ids_223_rgk),
            "UNIQUE_615": len(ids_615),
            "44_NOTICE_FILES": by_contour.get("44_NOTICE", 0),
            "44_RGK_FILES": by_contour.get("44_RGK", 0),
            "223_NOTICE_FILES": by_contour.get("223_NOTICE", 0),
            "223_RGK_FILES": by_contour.get("223_RGK", 0),
            "615_FILES": by_contour.get("615", 0),
            "OTHER_FILES": by_contour.get("OTHER", 0),
        }

        rgk_files = [x for x in classified if x["contour"] == "44_RGK"]
        parsed_ok = 0
        parse_fail = 0
        missing_xml = 0
        xml_records = []
        for item in rgk_files:
            path = RGK_DIR / item["file_name"]
            if not path.is_file():
                missing_xml += 1
                continue
            try:
                record, _passes = parse_rgk_file(str(path), tags)
            except Exception:
                parse_fail += 1
                continue
            if record is None:
                parse_fail += 1
                continue
            parsed_ok += 1
            xml_records.append(record)
        out["rgk_xml_parse"] = {
            "files": len(rgk_files),
            "parsed_ok": parsed_ok,
            "parse_fail": parse_fail,
            "missing_xml": missing_xml,
            "unique_contract_numbers": len({r.contract_number for r in xml_records}),
        }

        numbers = list({r.contract_number for r in xml_records})
        db_44 = lookup_numbers(cur, TABLES_44, numbers) if numbers else {}
        db_44_values = lookup_44_values(cur, numbers) if numbers else {}
        cur.execute(
            """
            SELECT contract_number, reason FROM rgk_contract_unresolved
            WHERE fz_type = '44' AND contract_number = ANY(%s)
            """,
            (numbers or ["__none__"],),
        )
        unresolved = {str(n): reason for n, reason in cur.fetchall()}

        balance = Counter()
        mismatches = defaultdict(list)
        for record in xml_records:
            number = record.contract_number
            rows = db_44.get(number) or []
            if number in unresolved and not rows:
                balance["UNRESOLVED"] += 1
                continue
            if not rows:
                balance["MISSING"] += 1
                if len(mismatches["MISSING"]) < 20:
                    mismatches["MISSING"].append(number)
                continue
            # Prefer non-completed
            live_vals = db_44_values.get(number) or []
            row = (live_vals[0] if live_vals else rows[0])
            balance["FOUND_IN_REGISTRY"] += 1
            if row["table"] == "reestr_contract_44_fz_awarded":
                balance["IN_AWARDED"] += 1
            xml_price = _num(record.final_price)
            db_price = _num(row.get("final_price"))
            if xml_price is not None and db_price is not None and xml_price != db_price:
                balance["PRICE_MISMATCH"] += 1
                if len(mismatches["PRICE"]) < 15:
                    mismatches["PRICE"].append(
                        {"number": number, "xml": str(xml_price), "db": str(db_price), "table": row["table"]}
                    )
            else:
                balance["PRICE_MATCH"] += 1
            xml_okpd = record.okpd_id
            if xml_okpd and row.get("okpd_id") and int(xml_okpd) != int(row["okpd_id"]):
                balance["OKPD_MISMATCH"] += 1
            else:
                balance["OKPD_MATCH"] += 1
            if record.contractor_id and row.get("contractor_id") and int(record.contractor_id) != int(row["contractor_id"]):
                balance["CONTRACTOR_MISMATCH"] += 1
            else:
                balance["CONTRACTOR_MATCH"] += 1

        # Notice identity vs DB (filename numbers only; XML deleted).
        notice_nums = list(ids_44_notice)
        db_notice = lookup_numbers(cur, TABLES_44, notice_nums) if notice_nums else {}
        notice_found = sum(1 for n in ids_44_notice if n in db_notice)
        notice_missing = [n for n in sorted(ids_44_notice) if n not in db_notice]
        # Intentionally filtered: OKPD miss, empty auction_name. Count unresolved too.
        cur.execute(
            """
            SELECT COUNT(*) FROM rgk_contract_unresolved
            WHERE fz_type = '44' AND contract_number = ANY(%s)
            """,
            (notice_missing[:5000] or ["__none__"],),
        )
        notice_missing_unresolved = int(cur.fetchone()[0]) if notice_missing else 0

        nums_223 = list(ids_223_notice)
        db_223 = lookup_numbers(cur, TABLES_223, nums_223) if nums_223 else {}
        found_223 = sum(1 for n in ids_223_notice if n in db_223)
        missing_223 = [n for n in sorted(ids_223_notice) if n not in db_223]

        out["rgk_balance"] = dict(balance)
        out["rgk_mismatch_samples"] = {k: v for k, v in mismatches.items()}
        out["unresolved_count_for_parsed_rgk"] = len(unresolved)
        out["notice_44_filename_vs_db"] = {
            "unique_numbers": len(ids_44_notice),
            "found_in_registry": notice_found,
            "not_in_registry": len(notice_missing),
            "not_in_registry_sample": notice_missing[:20],
        }
        out["notice_223_filename_vs_db"] = {
            "unique_numbers": len(ids_223_notice),
            "found_in_registry": found_223,
            "not_in_registry": len(missing_223),
            "not_in_registry_sample": missing_223[:20],
        }

        # 615
        cur.execute(
            "SELECT COUNT(*) FROM reestr_contract_615_pp WHERE contract_number = ANY(%s)",
            (list(ids_615) or ["__none__"],),
        )
        out["pp615_filename_vs_db"] = {
            "unique_numbers": len(ids_615),
            "found": int(cur.fetchone()[0]),
        }

    (OUT / "phase4_identities.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
