#!/usr/bin/env python3
"""Parse S7 parser journal for 2026-08-13 archive/XML counts. Read-only."""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

OUT = Path("/tmp/eis_s7_correctness")
START = datetime.fromisoformat("2026-08-17T18:17:38+03:00")
END = datetime.fromisoformat("2026-08-17T19:16:13+03:00")

ARCH_DONE = re.compile(
    r"Скачивание завершено:\s+(\d+)/(\d+)\s+архивов\s+\((44-ФЗ|223-ФЗ|615-ПП),\s+регион\s+(\d+)\)"
)
ARCH_ONE = re.compile(
    r"Скачан и распакован архив\s+(\d+)/(\d+)\s+\((44-ФЗ|223-ФЗ|615-ПП),\s+регион\s+(\d+)\)"
)
FOUND_XML = re.compile(
    r"Найдено\s+(\d+)\s+XML файлов(?: для обработки)?\s+\(регион\s+(\d+)\)"
)
RGK_FOLDER = re.compile(
    r"RGK folder: files=(\d+) batches=(\d+) found=(\d+) changed=(\d+) unchanged=(\d+) "
    r"promoted=(\d+) inserted=(\d+) unresolved=(\d+) elapsed=([0-9.]+)s"
)
RGK_BATCH = re.compile(
    r"RGK batch: input=(\d+) duplicates=(\d+) found=(\d+) changed=(\d+) unchanged=(\d+) "
    r"promoted=(\d+) inserted=(\d+) unresolved=(\d+) elapsed=([0-9.]+)s"
)
NO_CONTRACT = re.compile(r"Не найден номер контракта в файле (\S+)")
ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})")


def in_window(line: str) -> bool:
    match = ISO.match(line)
    if not match:
        return False
    ts = datetime.fromisoformat(match.group(1))
    return START <= ts <= END


def main() -> None:
    text = subprocess.check_output(
        [
            "journalctl",
            "-u",
            "tendermonitor-eis-parser.service",
            "--since",
            "2026-08-17 18:17:00",
            "--until",
            "2026-08-17 19:17:00",
            "--no-pager",
            "-o",
            "short-iso",
        ],
        text=True,
        errors="replace",
    )
    archives = defaultdict(lambda: Counter())
    found_xml = []
    rgk_folders = []
    batch_sum = Counter()
    batches = 0
    no_contract = Counter()
    other_errors = []
    for line in text.splitlines():
        if not in_window(line):
            continue
        m = ARCH_DONE.search(line)
        if m:
            done, total, fz, region = m.groups()
            archives[(region, fz)]["done_logs"] += 1
            archives[(region, fz)]["last_done"] = int(done)
            archives[(region, fz)]["last_total"] = int(total)
        m = ARCH_ONE.search(line)
        if m:
            n, total, fz, region = m.groups()
            archives[(region, fz)]["one_logs"] += 1
        m = FOUND_XML.search(line)
        if m:
            found_xml.append({"n": int(m.group(1)), "region": m.group(2), "line": line[-180:]})
        m = RGK_FOLDER.search(line)
        if m:
            rgk_folders.append(
                {
                    "files": int(m.group(1)),
                    "batches": int(m.group(2)),
                    "found": int(m.group(3)),
                    "changed": int(m.group(4)),
                    "unchanged": int(m.group(5)),
                    "promoted": int(m.group(6)),
                    "inserted": int(m.group(7)),
                    "unresolved": int(m.group(8)),
                    "elapsed": float(m.group(9)),
                }
            )
        m = RGK_BATCH.search(line)
        if m:
            batches += 1
            batch_sum["input"] += int(m.group(1))
            batch_sum["duplicates"] += int(m.group(2))
            batch_sum["found"] += int(m.group(3))
            batch_sum["changed"] += int(m.group(4))
            batch_sum["unchanged"] += int(m.group(5))
            batch_sum["promoted"] += int(m.group(6))
            batch_sum["inserted"] += int(m.group(7))
            batch_sum["unresolved"] += int(m.group(8))
        m = NO_CONTRACT.search(line)
        if m:
            name = m.group(1)
            kind = name.split("_", 1)[0]
            no_contract[kind] += 1
        if " ERROR " in line and "Не найден номер контракта" not in line and "Структура XML" not in line:
            other_errors.append(line[-300:])

    archive_rows = []
    for (region, fz), c in sorted(archives.items(), key=lambda x: (int(x[0][0]), x[0][1])):
        archive_rows.append(
            {
                "region": region,
                "fz": fz,
                "done_logs": c["done_logs"],
                "one_logs": c["one_logs"],
                "last_done": c["last_done"],
                "last_total": c["last_total"],
            }
        )
    last_folder = rgk_folders[-1] if rgk_folders else {}
    first_folder = rgk_folders[0] if rgk_folders else {}
    out = {
        "archive_rows": archive_rows,
        "archive_sum_last_total": sum(r["last_total"] for r in archive_rows),
        "found_xml_events": found_xml,
        "found_xml_sum": sum(x["n"] for x in found_xml),
        "rgk_folder_events": len(rgk_folders),
        "rgk_folder_first_files": first_folder.get("files"),
        "rgk_folder_last_files": last_folder.get("files"),
        "rgk_folder_sum_found": sum(x["found"] for x in rgk_folders),
        "rgk_folder_sum_changed": sum(x["changed"] for x in rgk_folders),
        "rgk_folder_sum_inserted": sum(x["inserted"] for x in rgk_folders),
        "rgk_folder_sum_unresolved": sum(x["unresolved"] for x in rgk_folders),
        "rgk_batch_count": batches,
        "rgk_batch_sum": dict(batch_sum),
        "no_contract_by_prefix": dict(no_contract),
        "other_error_count": len(other_errors),
        "other_error_sample": other_errors[:40],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase2_journal.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in {"archive_rows", "found_xml_events", "other_error_sample"}}, indent=2, ensure_ascii=False))
    print("archive_rows", len(archive_rows), "found_xml_events", len(found_xml))


if __name__ == "__main__":
    main()
