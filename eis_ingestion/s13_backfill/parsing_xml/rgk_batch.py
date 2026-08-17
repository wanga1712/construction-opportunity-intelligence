"""Bounded batch processing for S7 forward 44-FZ RGK XML."""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from database_work.database_operations import DatabaseOperations
from database_work.rgk_batch_store import RgkBatchStore
from parsing_xml.rgk_record import canonical_source_key, parse_rgk_file
from secondary_functions import load_config
from utils.logger_config import get_logger
from utils.source_day_metrics import emit

logger = get_logger()

DEFAULT_BATCH_SIZE = 500
MIN_BATCH_SIZE = 100
MAX_BATCH_SIZE = 2000


def rgk_batch_size() -> int:
    raw = os.getenv("TENDERMONITOR_RGK_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_BATCH_SIZE
    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, value))


def _chunks(items, size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _load_44_tags() -> dict:
    config = load_config()
    tags_path = config.get("tags", "get_tags_44_recouped")
    with open(tags_path, "r", encoding="utf-8") as handle:
        tags = json.load(handle)
    if not tags:
        raise ValueError("Не удалось загрузить теги 44-ФЗ RGK")
    return tags


def process_44_rgk_folder(folder_path: str, progress_manager=None, db_manager=None) -> dict:
    xml_files = sorted(name for name in os.listdir(folder_path) if name.endswith(".xml"))
    if not xml_files:
        return {"input": 0, "batches": 0}

    tags = _load_44_tags()
    ops = DatabaseOperations() if db_manager is None else DatabaseOperations(db_manager=db_manager)
    store = RgkBatchStore(ops.db_manager)
    totals = {
        "input": 0,
        "duplicates": 0,
        "found": 0,
        "changed": 0,
        "unchanged": 0,
        "promoted": 0,
        "inserted": 0,
        "unresolved": 0,
        "batches": 0,
        "parse_passes": 0,
        "selects": 0,
        "updates": 0,
        "commits": 0,
    }
    batch_size = rgk_batch_size()
    folder_started = time.perf_counter()
    known: set[str] = set()
    for names in _chunks(xml_files, batch_size):
        known |= store.lookup_filenames(names)

    records: list = []
    parse_passes = 0
    for name in xml_files:
        if name in known:
            continue
        path = os.path.join(folder_path, name)
        try:
            record, passes = parse_rgk_file(path, tags)
            parse_passes += passes
            if record is None:
                logger.error("Не найден номер контракта в файле %s", name)
                continue
            records.append(record)
        except Exception as exc:
            parse_passes += 1
            logger.error("Ошибка при обработке файла %s: %s", name, exc)

    records.sort(key=canonical_source_key)
    from parsing_xml.xml_parser_recouped_contract import _non_target_version_cache

    if progress_manager and hasattr(progress_manager, "tasks") and "process_all" in getattr(
        progress_manager, "tasks", {}
    ) and known:
        progress_manager.update_task("process_all", advance=len(known))

    for batch_records in _chunks(records, batch_size):
        metrics = _apply_parsed_batch(batch_records, store, _non_target_version_cache)
        totals["batches"] += 1
        for key in totals:
            if key in {"batches", "input", "duplicates", "parse_passes"}:
                continue
            totals[key] += int(metrics.get(key, 0))
        if progress_manager and hasattr(progress_manager, "tasks") and "process_all" in getattr(
            progress_manager, "tasks", {}
        ):
            progress_manager.update_task("process_all", advance=len(batch_records))

    totals["input"] = len(xml_files)
    totals["duplicates"] = len(known)
    totals["parse_passes"] = parse_passes
    if xml_files and totals["batches"] == 0:
        totals["batches"] = 1

    elapsed = time.perf_counter() - folder_started
    logger.info(
        "RGK folder: files={} batches={} found={} changed={} unchanged={} "
        "promoted={} inserted={} unresolved={} elapsed={:.1f}s",
        totals["input"],
        totals["batches"],
        totals["found"],
        totals["changed"],
        totals["unchanged"],
        totals["promoted"],
        totals["inserted"],
        totals["unresolved"],
        elapsed,
    )
    emit(
        "rgk_44_folder",
        files=len(xml_files),
        batches=totals["batches"],
        found=totals["found"],
        changed=totals["changed"],
        unchanged=totals["unchanged"],
        elapsed_sec=round(elapsed, 3),
    )
    return totals


def _apply_parsed_batch(records: list, store: RgkBatchStore, version_cache) -> dict:
    started = time.perf_counter()
    counter = store.counter
    selects0, updates0, commits0 = counter.selects, counter.updates, counter.commits
    numbers = [record.contract_number for record in records]
    codes: list[str] = []
    inns: list[str] = []
    for record in records:
        codes.extend(record.okpd_codes)
        if record.contractor_inn:
            inns.append(record.contractor_inn)

    okpd_map = store.lookup_okpd(codes)
    contractor_map = store.lookup_contractors(inns)
    registry_map = store.lookup_registry(numbers)
    unresolved_map = store.lookup_unresolved(numbers)
    plan = store.apply(
        records,
        known_filenames=set(),
        okpd_map=okpd_map,
        contractor_map=contractor_map,
        registry_map=registry_map,
        unresolved_map=unresolved_map,
        version_cache=version_cache,
    )
    plan.metrics["input"] = len(records)

    elapsed = time.perf_counter() - started
    metrics = dict(plan.metrics)
    metrics["selects"] = counter.selects - selects0
    metrics["updates"] = counter.updates - updates0
    metrics["commits"] = counter.commits - commits0
    logger.info(
        "RGK batch: input={} duplicates={} found={} changed={} unchanged={} "
        "promoted={} inserted={} unresolved={} elapsed={:.1f}s",
        metrics.get("input", 0),
        metrics.get("duplicates", 0),
        metrics.get("found", 0),
        metrics.get("changed", 0),
        metrics.get("unchanged", 0),
        metrics.get("promoted", 0),
        metrics.get("inserted", 0),
        metrics.get("unresolved", 0),
        elapsed,
    )
    return metrics
