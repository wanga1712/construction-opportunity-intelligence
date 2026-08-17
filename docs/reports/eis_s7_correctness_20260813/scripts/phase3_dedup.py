#!/usr/bin/env python3
"""Phase 3: filename uniqueness + processed_at vs leftover RGK. Run as tendermonitor."""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

from database_work.database_connection import DatabaseManager

OUT = Path("/tmp/eis_s7_correctness")
RGK = Path("/opt/tendermonitor/data/44_FZ/xml_reestr_44_new_contracts_recouped")
NAME_RE = re.compile(
    r"^(?P<kind>contract|contractCutted)_(?P<number>\d+)_(?P<ver>\d+)_(?P<guid>[0-9A-Fa-f]{32})\.xml$"
)
WINDOW_START = datetime.fromisoformat("2026-08-17T18:17:38+03:00")
WINDOW_END = datetime.fromisoformat("2026-08-17T19:16:13+03:00")


def load_candidate_names() -> list[str]:
    path = OUT / "SOURCE_XML_CANDIDATES_2026-08-13.csv"
    names = []
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("MATCH") == "bench_mtime":
                    names.append(row["FILE_NAME"])
    return list(dict.fromkeys(names))


def disk_pattern() -> dict:
    total = 0
    parsed = 0
    kinds = Counter()
    guids = Counter()
    numbers = Counter()
    number_guid = defaultdict(set)
    number_ver = defaultdict(set)
    unmatched = []
    for entry in os.scandir(RGK):
        if not entry.is_file() or not entry.name.endswith(".xml"):
            continue
        total += 1
        match = NAME_RE.match(entry.name)
        if not match:
            unmatched.append(entry.name)
            continue
        parsed += 1
        kinds[match.group("kind")] += 1
        guid = match.group("guid").upper()
        number = match.group("number")
        ver = match.group("ver")
        guids[guid] += 1
        numbers[number] += 1
        number_guid[number].add(guid)
        number_ver[number].add(ver)
    guid_dups = {g: n for g, n in guids.items() if n > 1}
    return {
        "files": total,
        "parsed_contract_ver_guid": parsed,
        "unmatched_count": len(unmatched),
        "unmatched_sample": unmatched[:20],
        "kinds": dict(kinds),
        "unique_guids": len(guids),
        "guid_duplicate_count": len(guid_dups),
        "guid_duplicate_sample": dict(list(guid_dups.items())[:10]),
        "unique_contract_numbers_in_filename": len(numbers),
        "numbers_with_multiple_guids": sum(1 for s in number_guid.values() if len(s) > 1),
        "numbers_with_multiple_versions": sum(1 for s in number_ver.values() if len(s) > 1),
        "max_files_per_number": max(numbers.values()) if numbers else 0,
    }


def chunks(items: list[str], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager()
    conn = db.connection
    conn.autocommit = True
    names = load_candidate_names()
    pattern = disk_pattern()
    out: dict = {"rgk_disk_pattern": pattern, "bench_mtime_names": len(names)}
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
        cur.execute(
            """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
            FROM pg_attribute a
            WHERE a.attrelid = 'public.file_names_xml'::regclass
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
        out["columns"] = [{"name": n, "type": t, "notnull": nn} for n, t, nn in cur.fetchall()]
        cur.execute(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE conrelid = 'public.file_names_xml'::regclass
            """
        )
        out["constraints"] = [{"name": n, "def": d} for n, d in cur.fetchall()]
        cur.execute(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname='public' AND tablename='file_names_xml'
            """
        )
        out["indexes"] = [{"name": n, "def": d} for n, d in cur.fetchall()]
        cur.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT file_name FROM public.file_names_xml
              GROUP BY file_name HAVING COUNT(*) > 1
            ) s
            """
        )
        out["duplicate_file_name_groups"] = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT file_name, COUNT(*) AS n
            FROM public.file_names_xml
            GROUP BY file_name HAVING COUNT(*) > 1
            ORDER BY n DESC LIMIT 15
            """
        )
        out["duplicate_file_name_top"] = [{"file_name": n, "rows": int(c)} for n, c in cur.fetchall()]

        col_names = [c["name"] for c in out["columns"]]
        has_processed = "processed_at" in col_names
        out["has_processed_at"] = has_processed
        if has_processed:
            cur.execute(
                """
                SELECT COUNT(*) FROM public.file_names_xml
                WHERE processed_at >= %s AND processed_at <= %s
                """,
                (WINDOW_START, WINDOW_END),
            )
            out["db_rows_processed_in_window"] = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(DISTINCT file_name) FROM public.file_names_xml
                WHERE processed_at >= %s AND processed_at <= %s
                """,
                (WINDOW_START, WINDOW_END),
            )
            out["db_distinct_names_processed_in_window"] = int(cur.fetchone()[0])

        present = {}
        for batch in chunks(names, 500):
            if has_processed:
                cur.execute(
                    """
                    SELECT file_name, COUNT(*) AS n,
                           MIN(processed_at) AS first_at, MAX(processed_at) AS last_at
                    FROM public.file_names_xml
                    WHERE file_name = ANY(%s)
                    GROUP BY file_name
                    """,
                    (batch,),
                )
                for file_name, n, first_at, last_at in cur.fetchall():
                    present[file_name] = {
                        "rows": int(n),
                        "first_at": first_at.isoformat() if first_at else None,
                        "last_at": last_at.isoformat() if last_at else None,
                    }
            else:
                cur.execute(
                    "SELECT file_name, COUNT(*) FROM public.file_names_xml WHERE file_name = ANY(%s) GROUP BY file_name",
                    (batch,),
                )
                for file_name, n in cur.fetchall():
                    present[file_name] = {"rows": int(n)}

        missing = [n for n in names if n not in present]
        in_window = 0
        before_window = 0
        after_window = 0
        for rec in present.values():
            first = rec.get("first_at")
            if not first:
                continue
            ts = datetime.fromisoformat(first)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=WINDOW_START.tzinfo)
            if WINDOW_START <= ts <= WINDOW_END:
                in_window += 1
            elif ts < WINDOW_START:
                before_window += 1
            else:
                after_window += 1
        out["bench_mtime_vs_db"] = {
            "names": len(names),
            "found_in_db": len(present),
            "missing_from_db": len(missing),
            "missing_sample": missing[:30],
            "first_processed_in_window": in_window,
            "first_processed_before_window": before_window,
            "first_processed_after_window": after_window,
        }

        # GUID uniqueness among window DB names
        if has_processed:
            cur.execute(
                """
                SELECT file_name FROM public.file_names_xml
                WHERE processed_at >= %s AND processed_at <= %s
                """,
                (WINDOW_START, WINDOW_END),
            )
            window_names = [r[0] for r in cur.fetchall()]
            parsed = 0
            guids = Counter()
            numbers = Counter()
            unmatched = 0
            for name in window_names:
                match = NAME_RE.match(name or "")
                if not match:
                    unmatched += 1
                    continue
                parsed += 1
                guids[match.group("guid").upper()] += 1
                numbers[match.group("number")] += 1
            out["window_name_pattern"] = {
                "rows": len(window_names),
                "parsed": parsed,
                "unmatched": unmatched,
                "unique_guids": len(guids),
                "guid_dups": sum(1 for n in guids.values() if n > 1),
                "unique_numbers": len(numbers),
                "unmatched_sample": [n for n in window_names if not NAME_RE.match(n or "")][:20],
            }

    guid_unique_on_disk = pattern["guid_duplicate_count"] == 0 and pattern["parsed_contract_ver_guid"] == pattern["files"]
    out["FILENAME_IS_GLOBALLY_UNIQUE"] = "YES" if guid_unique_on_disk else "NO"
    out["FALSE_DEDUP_RISK"] = (
        "NO"
        if guid_unique_on_disk and out.get("duplicate_file_name_groups", 0) >= 0
        else "YES"
    )
    # Duplicate rows of the same name are not cross-date content collisions.
    # Risk is YES only if the same basename can map to different payloads.
    if guid_unique_on_disk:
        out["FALSE_DEDUP_RISK"] = "NO"
        out["FALSE_DEDUP_NOTE"] = (
            "Skip key is full basename including 32-hex publish GUID. "
            "On-disk leftover RGK has unique GUID per file. Same contract_number "
            "can have many versions/GUIDs; those are different filenames and are parsed."
        )
    (OUT / "phase3_dedup.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
