#!/usr/bin/env python3
"""Compare canonical 2026-08-13 RGK dates vs any registry row. Read-only."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager
from parsing_xml.rgk_record import parse_rgk_file
from secondary_functions import load_config

OUT = Path("/tmp/eis_s7_correctness")
RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
WINDOW_START = datetime.fromisoformat("2026-08-17T18:17:38+03:00")
WINDOW_END = datetime.fromisoformat("2026-08-17T19:16:13+03:00")


def filename_key(file_name: str) -> tuple:
    parts = Path(file_name).name.split("_")
    version = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 0
    guid = parts[3].split(".")[0].upper() if len(parts) >= 4 else ""
    return (version, guid)
TABLES = [
    "reestr_contract_44_fz",
    "reestr_contract_44_fz_awarded",
    "reestr_contract_44_fz_commission_work",
    "reestr_contract_44_fz_unknown",
    "reestr_contract_44_fz_unclear",
]


def norm_date(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:10]


def main() -> None:
    tags = json.loads(Path(load_config().get("tags", "get_tags_44_recouped")).read_text(encoding="utf-8"))
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT file_name FROM public.file_names_xml
            WHERE processed_at >= %s AND processed_at <= %s
              AND file_name LIKE 'contract_%%'
            """,
            (WINDOW_START, WINDOW_END),
        )
        names = [r[0] for r in cur.fetchall()]
    by_number: dict[str, list] = {}
    missing_files = 0
    for name in names:
        path = RGK / name
        if not path.is_file():
            missing_files += 1
            continue
        record, _ = parse_rgk_file(str(path), tags)
        if record is None:
            continue
        by_number.setdefault(record.contract_number, []).append(record)

    canonical = {}
    for number, recs in by_number.items():
        recs.sort(key=lambda rec: filename_key(rec.file_name))
        canonical[number] = recs[-1]

    numbers = list(canonical)
    db_dates: dict[str, list[tuple[str, str | None, str | None]]] = {n: [] for n in numbers}
    with conn.cursor() as cur:
        for table in TABLES:
            for i in range(0, len(numbers), 500):
                batch = numbers[i : i + 500]
                try:
                    cur.execute(
                        f"""
                        SELECT contract_number, delivery_start_date::text, delivery_end_date::text
                        FROM {table}
                        WHERE contract_number = ANY(%s)
                        """,
                        (batch,),
                    )
                except Exception:
                    continue
                for number, start, end in cur.fetchall():
                    db_dates[str(number)].append((table, norm_date(start), norm_date(end)))

    start_match = end_match = start_miss = end_miss = no_row = 0
    samples = []
    awarded_dup = 0
    for number, rec in canonical.items():
        rows = db_dates.get(number) or []
        if not rows:
            no_row += 1
            continue
        awarded = [r for r in rows if r[0].endswith("_awarded")]
        if len(awarded) > 1:
            awarded_dup += 1
        xml_start, xml_end = norm_date(rec.delivery_start_date), norm_date(rec.delivery_end_date)
        starts = {r[1] for r in rows if r[1]}
        ends = {r[2] for r in rows if r[2]}
        if xml_start and xml_start not in starts:
            start_miss += 1
            if len(samples) < 8:
                samples.append({"number": number, "field": "start", "xml": xml_start, "db": sorted(starts)})
        else:
            start_match += 1
        if xml_end and xml_end not in ends:
            end_miss += 1
            if len(samples) < 8:
                samples.append({"number": number, "field": "end", "xml": xml_end, "db": sorted(ends)})
        else:
            end_match += 1

    out = {
        "window_files": len(names),
        "missing_files": missing_files,
        "unique_xml_numbers": len(canonical),
        "no_registry_row": no_row,
        "start_match": start_match,
        "start_miss": start_miss,
        "end_match": end_match,
        "end_miss": end_miss,
        "duplicate_awarded_numbers": awarded_dup,
        "samples": samples,
    }
    (OUT / "phaseF_dates.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
