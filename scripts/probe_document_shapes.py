"""Замер форм таблиц в документах закупок (read-only). Основа каталога шаблонов.

Показывает, какие формы таблиц реально встречаются в корпусе: семейство
(смета / комбинированное ТЗ / плоское ТЗ / требования), подписи шапки, есть ли
колонка товара, есть ли строки-заголовки позиций (одна заполненная ячейка).

Запуск на S13 (прод-окружение задаёт .env):
    bash scratch/_run_py.sh scripts/probe_document_shapes.py --limit 60

По умолчанию — БЕЗОПАСНЫЙ режим: читает только уже готовый кэш разбора
(`/var/cache/crm_direct_parse`), не вызывает парсеры и ничего не пишет. Так
замер можно прогонять даже при работающих воркерах. Флаг `--allow-parse`
разрешает разбирать файлы воркерным парсером (и писать кэш) — только когда
документные демоны остановлены.

В БД ничего не пишет: только читает `document_files`.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.getenv("CRM_ROOT", "/opt/CRM_Streamlit"))

from src.services import direct_document_extractor as dx  # noqa: E402


def _procurement_paths(limit: int) -> dict:
    """procurement_id -> [local_path] по COMPLETED-документам (read-only)."""
    conn = dx._di_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT procurement_id, local_path FROM document_files
                   WHERE download_status = 'COMPLETED' AND local_path IS NOT NULL
                     AND procurement_id IS NOT NULL
                   ORDER BY procurement_id DESC, id""",
            )
            out: dict = collections.OrderedDict()
            for pid, path in cur.fetchall():
                bucket = out.setdefault(int(pid), [])
                if path and path not in bucket:
                    bucket.append(path)
            return dict(list(out.items())[:limit])
    finally:
        conn.close()


def _shape_of_table(rows, name):
    kind, offset = dx._classify_with_offset(rows)
    if not kind:
        return None
    header = [dx._norm_cell(c) for c in rows[offset]]
    header_low = [h.lower() for h in header]
    data_rows = rows[offset + 1:]
    single_cell = 0
    samples = []
    for row in data_rows:
        filled = [dx._norm_cell(c) for c in row if dx._norm_cell(c)]
        if len(filled) == 1:
            single_cell += 1
        elif filled and len(samples) < 3:
            samples.append(" | ".join(filled)[:120])
    return {
        "signature": "%s | %d cols | %s" % (kind, len(header), " ".join(header_low)[:160]),
        "kind": kind,
        "header": header,
        "item_col": dx._find_item_col(header_low),
        "data_rows": len(data_rows),
        "single_cell_rows": single_cell,
        "samples": samples,
        "file": name,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60, help="сколько закупок разобрать")
    parser.add_argument("--out", default="/tmp/doc_shapes.json")
    parser.add_argument("--allow-parse", action="store_true",
                        help="разбирать файлы воркерным парсером и писать кэш "
                             "(только при ОСТАНОВЛЕННЫХ воркерах)")
    args = parser.parse_args()

    per_proc = _procurement_paths(args.limit)
    shapes: dict = collections.OrderedDict()
    files_seen = files_parsed = files_cached = files_skipped = 0
    for paths in per_proc.values():
        if args.allow_parse:
            external = dx._external_docs(paths)
        else:
            # Безопасный режим: только готовый кэш разбора, парсеры не поднимаем.
            external = {}
            for path in paths:
                cached = dx._cache_read(path)
                if cached is not None:
                    external[path] = cached
                    files_cached += 1
                else:
                    files_skipped += 1
        for path in paths:
            doc = external.get(path)
            if not doc:
                continue
            files_seen += 1
            tables = doc.get("tables") or []
            if tables:
                files_parsed += 1
            for rows in tables:
                shape = _shape_of_table(rows, os.path.basename(path))
                if not shape:
                    continue
                entry = shapes.setdefault(shape["signature"], {
                    "kind": shape["kind"], "header": shape["header"],
                    "tables": 0, "with_item_col": 0, "with_position_blocks": 0,
                    "examples": [],
                })
                entry["tables"] += 1
                if shape["item_col"] >= 0:
                    entry["with_item_col"] += 1
                if shape["single_cell_rows"] > 1:
                    entry["with_position_blocks"] += 1
                if len(entry["examples"]) < 3:
                    entry["examples"].append(
                        {"file": shape["file"], "rows": shape["data_rows"],
                         "single_cell_rows": shape["single_cell_rows"],
                         "samples": shape["samples"]})

    payload = {
        "procurements": len(per_proc),
        "files_checked": files_seen,
        "files_with_tables": files_parsed,
        "model": "allow_parse" if args.allow_parse else "cache_only",
        "files_from_cache": files_cached,
        "files_skipped_not_cached": files_skipped,
        "shapes": list(shapes.values()),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("procurements=%d files=%d with_tables=%d shapes=%d model=%s cache=%d skipped=%d -> %s"
          % (len(per_proc), files_seen, files_parsed, len(shapes),
             payload["model"], files_cached, files_skipped, args.out))
    for entry in payload["shapes"]:
        print("  %4d tables | item_col %3d | pos_blocks %3d | %s"
              % (entry["tables"], entry["with_item_col"],
                 entry["with_position_blocks"], entry["header"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
