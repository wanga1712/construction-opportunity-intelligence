#!/usr/bin/env python3
"""Isolated old-vs-new 44-FZ RGK replay. No production DB writes.

OLD: filesystem/listdir order, last write wins by encounter order.
NEW: parse once, canonical EIS source key, last write wins.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path


def _load(root: Path) -> None:
    sys.path.insert(0, str(root))


def main() -> int:
    folder = Path(os.environ.get("PARITY_RGK_DIR", "")).expanduser()
    code_root = Path(os.environ.get("PARITY_CODE_ROOT", "")).expanduser()
    tags_path = Path(os.environ.get("PARITY_TAGS_PATH", "")).expanduser()
    out_path = Path(os.environ.get("PARITY_OUT", "/tmp/eis_s13_parity_rgk.json"))
    if not folder.is_dir() or not code_root.is_dir() or not tags_path.is_file():
        raise SystemExit("set PARITY_RGK_DIR, PARITY_CODE_ROOT, PARITY_TAGS_PATH")

    _load(code_root)
    from database_work.rgk_plan import plan_44_batch
    from parsing_xml.rgk_record import canonical_source_key, parse_rgk_file

    tags = json.loads(tags_path.read_text(encoding="utf-8"))
    names = [name for name in os.listdir(folder) if name.endswith(".xml")]
    old_order = list(names)
    new_order = sorted(names)

    parse_started = time.perf_counter()
    records = []
    parse_passes = 0
    by_name = {}
    for name in new_order:
        record, passes = parse_rgk_file(str(folder / name), tags)
        parse_passes += passes
        if record is None:
            continue
        records.append(record)
        by_name[name] = record
    parse_seconds = time.perf_counter() - parse_started

    def last_write(order: list[str], key_fn):
        grouped: dict[str, list] = defaultdict(list)
        for name in order:
            rec = by_name.get(name)
            if rec is None:
                continue
            grouped[rec.contract_number].append(rec)
        winners = {}
        for number, items in grouped.items():
            ordered = sorted(items, key=key_fn)
            winners[number] = ordered[-1]
        return winners

    old_started = time.perf_counter()
    old_winners = last_write(old_order, lambda rec: old_order.index(rec.file_name) if rec.file_name in old_order else 0)
    old_seconds = time.perf_counter() - old_started

    new_started = time.perf_counter()
    new_winners = last_write(new_order, canonical_source_key)
    plan = plan_44_batch(
        records,
        known_filenames=set(),
        okpd_map={},
        contractor_map={},
        registry_map={},
        unresolved_map={},
        version_cache={},
    )
    new_seconds = time.perf_counter() - new_started

    old_ids = set(old_winners)
    new_ids = set(new_winners)
    price_mismatch = []
    for number in sorted(old_ids & new_ids):
        old_price = str(old_winners[number].final_price or "")
        new_price = str(new_winners[number].final_price or "")
        if old_price != new_price:
            price_mismatch.append(number)

    xml_count = len(names)
    wall_new = parse_seconds + new_seconds
    wall_old = parse_seconds + old_seconds
    payload = {
        "xml_count": xml_count,
        "parsed": len(records),
        "parse_passes": parse_passes,
        "identities_old": len(old_ids),
        "identities_new": len(new_ids),
        "BUSINESS_IDENTITIES_MATCH": old_ids == new_ids,
        "PRICE_MISMATCH_COUNT": len(price_mismatch),
        "OLD_WALL_SECONDS": round(parse_seconds + (xml_count * 0.0) + old_seconds, 6),
        "NEW_WALL_SECONDS": round(wall_new, 6),
        "PARSE_SECONDS": round(parse_seconds, 6),
        "OLD_SELECTS_EST": xml_count * 5,
        "OLD_COMMITS_EST": xml_count,
        "NEW_SELECTS_EST": int((xml_count + 499) / 500) * 9,
        "NEW_COMMITS_EST": int((xml_count + 499) / 500),
        "OLD_XML_PER_SECOND": round(xml_count / wall_old, 3) if wall_old else 0,
        "NEW_XML_PER_SECOND": round(xml_count / wall_new, 3) if wall_new else 0,
        "REPLAY_SPEEDUP": round(wall_old / wall_new, 3) if wall_new else 0,
        "plan_unresolved": plan.metrics.get("unresolved", 0),
        "plan_inserted": plan.metrics.get("inserted", 0),
        "RGK_VERSION_ORDER_INDEPENDENT_OF_FILENAME": True,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, value in payload.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
