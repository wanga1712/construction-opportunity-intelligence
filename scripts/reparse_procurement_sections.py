#!/usr/bin/env python3
"""Разовый ДИАГНОСТИЧЕСКИЙ reparse section-полей для одной закупки.

ROAD_REPAIR_SECTION_TEMPLATES_V1 / Phase 2. Не использует claim-фильтр admission:
берёт уже скачанные файлы (`document_files.local_path`), парсит их и вызывает
`extract_and_persist` с `EMBEDDED_FORCE_UPDATE=1`, чтобы section-поля обновились
у СУЩЕСТВУЮЩИХ строк. Очередь/admission/scoring/medal не меняются.

    .venv313/bin/python scripts/reparse_procurement_sections.py --procurement-id 60467 --local-only           # dry-run
    .venv313/bin/python scripts/reparse_procurement_sections.py --procurement-id 60467 --local-only --apply   # запись
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg2
import psycopg2.extras


def _doc_conn():
    # Credentials приходят из воркерных EnvironmentFile (S13_DOCUMENT_DB_*),
    # поэтому скрипт запускается интерпретатором воркерного venv.
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
        connect_timeout=8,
    )


def _targets(conn, procurement_id: int):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT id, file_name, local_path, physical_download_key
          FROM document_files
         WHERE procurement_id = %s
           AND coalesce(local_path, '') <> ''
           AND local_deleted_at IS NULL
         ORDER BY id
        """,
        (procurement_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def _category_maps(conn, procurement_id: int):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT DISTINCT document_name, category_code FROM structured_extraction_runs"
        " WHERE procurement_id = %s AND category_code IS NOT NULL",
        (procurement_id,),
    )
    by_doc = {str(r["document_name"]): r["category_code"] for r in cur.fetchall()}
    cur.execute(
        "SELECT category_code, count(*) c FROM structured_entities"
        " WHERE procurement_id = %s AND category_code IS NOT NULL"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
        (procurement_id,),
    )
    row = cur.fetchone()
    return by_doc, (row["category_code"] if row else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procurement-id", type=int, required=True)
    ap.add_argument("--local-only", action="store_true",
                    help="только файлы, уже лежащие на диске (без скачивания)")
    ap.add_argument("--apply", action="store_true", help="по умолчанию dry-run")
    args = ap.parse_args()

    sys.path.insert(0, "/opt/tender_documents_research")

    conn = _doc_conn()
    try:
        rows = _targets(conn, args.procurement_id)
        by_doc, default_cat = _category_maps(conn, args.procurement_id)
    finally:
        conn.close()

    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row["local_path"])].append(row)

    present = {path: items for path, items in grouped.items() if os.path.exists(path)}
    missing = [path for path in grouped if not os.path.exists(path)]

    print("procurement:", args.procurement_id, "| document_files rows with local_path:",
          len(rows), "| distinct paths:", len(grouped))
    print("on disk:", len(present), "| missing:", len(missing), "| apply:", bool(args.apply))
    for path in missing[:5]:
        print("   MISSING:", path)
    if not args.local_only:
        print("NOTE: --local-only не задан; скрипт всё равно не скачивает файлы.")

    if not present:
        print("NOTHING_TO_DO: нет локально присутствующих файлов")
        return 0
    if not args.apply:
        for path, items in present.items():
            name = Path(path).name
            print("   WOULD_PARSE:", name, "| document_files ids:",
                  [i["id"] for i in items], "| category:",
                  by_doc.get(name, default_cat))
        print("DRY_RUN OK: DB_WRITES=0")
        return 0

    os.environ["EMBEDDED_FORCE_UPDATE"] = "1"   # обновлять существующие строки
    from document_processor.parse_extractors import extract_and_persist
    from document_processor.parse_utils import (
        get_rich_parser, parse_file_with_meta, supports_rich_meta,
    )
    from document_processor.parser_factory import ParserFactory

    factory = ParserFactory()
    totals = Counter()
    for path, items in present.items():
        file_path = Path(path)
        name = file_path.name
        category = by_doc.get(name, default_cat)
        parser = (get_rich_parser(factory, file_path) if supports_rich_meta(file_path)
                  else factory.get_parser(file_path))
        if parser is None:
            print("   SKIP (no parser):", name)
            continue
        text, line_meta = parse_file_with_meta(parser, file_path)
        for item in items:
            result = extract_and_persist(
                file_path, text, args.procurement_id, name,
                category_code=category,
                source_document_id=item["id"],
                physical_key=item["physical_download_key"],
                line_meta=line_meta,
            )
            for key, value in (result or {}).items():
                totals[key] += int(value or 0)
            print("   PARSED:", name, "| df_id:", item["id"], "| cat:", category,
                  "| result:", result)
    print("TOTALS:", dict(totals))
    print("APPLIED: section-поля пересчитаны (EMBEDDED_FORCE_UPDATE=1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
