#!/usr/bin/env python3
"""Phase 2/3 disk+journal inventory for 2026-08-13. Read-only. No secrets."""
from __future__ import annotations

import configparser
import csv
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from stat import S_ISREG

ROOT = Path("/opt/tendermonitor")
OUT = Path("/tmp/eis_s7_correctness")
BENCH_START = datetime.fromisoformat("2026-08-17T18:17:38+03:00")
BENCH_FINISH = datetime.fromisoformat("2026-08-17T19:16:13+03:00")
DATE_TOKEN = "20260813"
DATE_HYPHEN = "2026-08-13"
SECRET_KEYS = re.compile(r"(token|password|secret|passwd|key)", re.I)
XML_DATE = re.compile(r"(20\d{6})")
XML_REGION = re.compile(r"(?:_|\b)(\d{1,2}|9[0-4])(?:_|\.)")


def load_paths() -> dict[str, str]:
    cfg = configparser.ConfigParser()
    cfg.read(ROOT / "config.ini", encoding="utf-8")
    wanted = {}
    mapping = [
        ("path", "reest_new_contract_archive_44_fz_xml", "44_NOTICE"),
        ("path", "recouped_contract_archive_44_fz_xml", "44_RGK"),
        ("path", "reest_new_contract_archive_223_fz_xml", "223_NOTICE"),
        ("path", "recouped_contract_archive_223_fz_xml", "223_RGK"),
        ("eis_615", "archive_xml", "615"),
    ]
    for section, key, label in mapping:
        if cfg.has_option(section, key):
            wanted[label] = cfg.get(section, key)
    return wanted


def file_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone()


def classify_xml_name(name: str) -> dict:
    dates = XML_DATE.findall(name)
    return {
        "name": name,
        "has_20260813": DATE_TOKEN in name or DATE_HYPHEN in name,
        "embedded_dates": dates[:4],
        "prefix": name.split("_", 1)[0][:40],
    }


def walk_folder(label: str, folder: str) -> dict:
    path = Path(folder)
    out = {
        "label": label,
        "path": folder,
        "exists": path.is_dir(),
        "xml": 0,
        "zip": 0,
        "xml_bytes": 0,
        "zip_bytes": 0,
        "xml_in_bench_mtime": 0,
        "xml_named_20260813": 0,
        "zip_named_20260813": 0,
        "prefixes": Counter(),
        "embedded_date_counts": Counter(),
        "bench_files": [],
        "named_20260813": [],
        "sample_names": [],
    }
    if not path.is_dir():
        return out
    names = []
    for entry in os.scandir(path):
        if not entry.is_file():
            continue
        name = entry.name
        st = entry.stat()
        if name.endswith(".xml"):
            out["xml"] += 1
            out["xml_bytes"] += st.st_size
            names.append(name)
            info = classify_xml_name(name)
            out["prefixes"][info["prefix"]] += 1
            for d in info["embedded_dates"]:
                out["embedded_date_counts"][d] += 1
            mtime = datetime.fromtimestamp(st.st_mtime).astimezone()
            rec = {
                "name": name,
                "size": st.st_size,
                "mtime": mtime.isoformat(timespec="seconds"),
                "embedded_dates": info["embedded_dates"],
            }
            if BENCH_START <= mtime <= BENCH_FINISH:
                out["xml_in_bench_mtime"] += 1
                out["bench_files"].append(rec)
            if info["has_20260813"]:
                out["xml_named_20260813"] += 1
                out["named_20260813"].append(rec)
        elif name.endswith(".zip"):
            out["zip"] += 1
            out["zip_bytes"] += st.st_size
            if DATE_TOKEN in name or DATE_HYPHEN in name:
                out["zip_named_20260813"] += 1
    names.sort()
    out["sample_names"] = names[:20] + (names[-5:] if len(names) > 25 else [])
    out["prefixes"] = dict(out["prefixes"].most_common(15))
    out["embedded_date_counts"] = dict(out["embedded_date_counts"].most_common(20))
    return out


def sha256_file(path: Path, limit: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        remaining = limit
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def collision_report(folder: str, records: list[dict]) -> dict:
    """Same basename on disk cannot collide; check date tokens vs uniqueness pattern."""
    by_stem = defaultdict(list)
    for rec in records:
        by_stem[rec["name"]].append(rec)
    dup_names = {k: v for k, v in by_stem.items() if len(v) > 1}
    return {"duplicate_basenames_in_folder": len(dup_names)}


def journal_window() -> dict:
    cmd = [
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
    ]
    try:
        text = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, errors="replace")
    except subprocess.CalledProcessError as exc:
        return {"error": "journalctl_failed", "returncode": exc.returncode}
    lines = text.splitlines()
    interesting = []
    counts = Counter()
    archive_lines = []
    error_lines = []
    for line in lines:
        low = line.lower()
        if "скачан и распакован архив" in low or "скачивание завершено" in low:
            archive_lines.append(line)
            counts["archive_log"] += 1
        if "ошибка" in low or "error" in low or "exception" in low:
            error_lines.append(line)
            counts["error_like"] += 1
        if "rgk batch:" in low:
            counts["rgk_batch"] += 1
        if "rgk folder:" in low:
            counts["rgk_folder"] += 1
        if "начало обработки" in low:
            counts["process_start"] += 1
    return {
        "journal_lines": len(lines),
        "counts": dict(counts),
        "archive_lines_sample": archive_lines[:30],
        "archive_lines_tail": archive_lines[-10:],
        "error_lines_sample": error_lines[:40],
        "archive_line_count": len(archive_lines),
        "error_line_count": len(error_lines),
    }


def metrics_summary() -> dict:
    path = ROOT / "source_day_metrics.jsonl"
    rows = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if rec.get("source_date") == DATE_HYPHEN or (
                rec.get("event") == "rgk_44_folder"
                and rec.get("ts", "") >= "2026-08-17T18:17:38"
                and rec.get("ts", "") <= "2026-08-17T19:16:13"
            ):
                rows.append(rec)
    regions = [r for r in rows if r.get("event") == "region_complete" and r.get("source_date") == DATE_HYPHEN]
    objects = Counter()
    for r in regions:
        for k, v in (r.get("objects") or {}).items():
            objects[k] += int(v or 0)
    return {
        "region_complete": len(regions),
        "sum_archives": sum(int(r.get("archives") or 0) for r in regions),
        "sum_fz44_sec": round(sum(float(r.get("fz44_sec") or 0) for r in regions), 3),
        "sum_fz223_sec": round(sum(float(r.get("fz223_sec") or 0) for r in regions), 3),
        "objects_sum": dict(objects),
        "regions": [
            {
                "region": r.get("region"),
                "archives": r.get("archives"),
                "elapsed_sec": r.get("elapsed_sec"),
                "fz44_sec": r.get("fz44_sec"),
                "fz223_sec": r.get("fz223_sec"),
                "pp615_sec": r.get("pp615_sec"),
                "objects": r.get("objects") or {},
            }
            for r in regions
        ],
    }


def write_csv(folder_stats: list[dict], metrics: dict) -> None:
    path = OUT / "SOURCE_INPUT_2026-08-13.csv"
    # Per-region from metrics; disk totals as footer comments in companion json.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "REGION",
                "ARCHIVES_METRIC",
                "FZ44_SEC",
                "FZ223_SEC",
                "PP615_SEC",
                "FILE_NAMES_XML",
                "FILES_PROCESSED",
                "LINKS_44",
                "LINKS_223",
                "CONTRACTS_44",
                "CONTRACTS_223",
                "CONTRACTS_615",
            ],
        )
        writer.writeheader()
        for row in metrics.get("regions", []):
            obj = row.get("objects") or {}
            writer.writerow(
                {
                    "REGION": row.get("region"),
                    "ARCHIVES_METRIC": row.get("archives"),
                    "FZ44_SEC": row.get("fz44_sec"),
                    "FZ223_SEC": row.get("fz223_sec"),
                    "PP615_SEC": row.get("pp615_sec"),
                    "FILE_NAMES_XML": obj.get("file_names_xml", 0),
                    "FILES_PROCESSED": obj.get("files_processed", 0),
                    "LINKS_44": obj.get("links_documentation_44_fz", 0),
                    "LINKS_223": obj.get("links_documentation_223_fz", 0),
                    "CONTRACTS_44": obj.get("reestr_contract_44_fz", 0),
                    "CONTRACTS_223": obj.get("reestr_contract_223_fz", 0),
                    "CONTRACTS_615": obj.get("reestr_contract_615_pp", 0),
                }
            )


def hash_subset(folder: str, records: list[dict], cap: int = 400) -> list[dict]:
    path = Path(folder)
    out = []
    for rec in records[:cap]:
        fp = path / rec["name"]
        if not fp.is_file():
            continue
        item = dict(rec)
        item["sha256_8m"] = sha256_file(fp)
        out.append(item)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = load_paths()
    folder_stats = []
    for label, folder in paths.items():
        stats = walk_folder(label, folder)
        folder_stats.append(stats)
    metrics = metrics_summary()
    journal = journal_window()
    write_csv(folder_stats, metrics)
    xml_list = OUT / "SOURCE_XML_CANDIDATES_2026-08-13.csv"
    with xml_list.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["CONTOUR", "MATCH", "FILE_NAME", "SIZE", "MTIME", "EMBEDDED_DATES"],
        )
        writer.writeheader()
        for stats in folder_stats:
            for rec in stats.get("bench_files") or []:
                writer.writerow(
                    {
                        "CONTOUR": stats["label"],
                        "MATCH": "bench_mtime",
                        "FILE_NAME": rec["name"],
                        "SIZE": rec["size"],
                        "MTIME": rec["mtime"],
                        "EMBEDDED_DATES": "|".join(rec.get("embedded_dates") or []),
                    }
                )
            for rec in stats.get("named_20260813") or []:
                writer.writerow(
                    {
                        "CONTOUR": stats["label"],
                        "MATCH": "filename_20260813",
                        "FILE_NAME": rec["name"],
                        "SIZE": rec["size"],
                        "MTIME": rec["mtime"],
                        "EMBEDDED_DATES": "|".join(rec.get("embedded_dates") or []),
                    }
                )

    hashed = {}
    for stats in folder_stats:
        if stats["label"] in {"44_RGK", "44_NOTICE", "223_NOTICE", "223_RGK", "615"}:
            hashed[stats["label"]] = {
                "bench_mtime_hashed": hash_subset(stats["path"], stats["bench_files"], cap=250),
                "named_20260813_hashed": hash_subset(stats["path"], stats["named_20260813"], cap=250),
            }

    slim = []
    for stats in folder_stats:
        slim.append(
            {
                k: v
                for k, v in stats.items()
                if k not in {"bench_files", "named_20260813"}
            }
            | {
                "bench_files_count": len(stats["bench_files"]),
                "named_20260813_count": len(stats["named_20260813"]),
                "bench_files_sample": stats["bench_files"][:15],
                "named_20260813_sample": stats["named_20260813"][:15],
            }
        )

    payload = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "benchmark_window": {
            "start": BENCH_START.isoformat(),
            "finish": BENCH_FINISH.isoformat(),
            "source_date": DATE_HYPHEN,
        },
        "paths": paths,
        "folders": slim,
        "metrics": {
            "region_complete": metrics["region_complete"],
            "sum_archives": metrics["sum_archives"],
            "objects_sum": metrics["objects_sum"],
            "sum_fz44_sec": metrics["sum_fz44_sec"],
            "sum_fz223_sec": metrics["sum_fz223_sec"],
        },
        "journal": journal,
        "hash_note": "sha256 of first 8MiB; subsets capped at 250 per class",
        "hashed_counts": {k: {kk: len(vv) for kk, vv in v.items()} for k, v in hashed.items()},
    }
    (OUT / "phase2_inventory.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "phase2_hashes.json").write_text(
        json.dumps(hashed, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "phase2_regions.json").write_text(
        json.dumps(metrics["regions"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
