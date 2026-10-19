#!/usr/bin/env python3
"""Точечное out-of-order скачивание одного document_files по id.

Использует штатный downloader (DownloadCoordinator/HttpFileClient) и
обновляет document_files через state_repo. Не меняет admission, scoring,
medal или статус очереди.

    --document-file-id 24567 --apply
Без --apply — dry-run (показывает URL/имя/статус, ничего не качает).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
if str(ROOT / "tender_documents_research") not in sys.path:
    sys.path.insert(0, str(ROOT / "tender_documents_research"))


def di_dsn():
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def fetch(conn, doc_id: int):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT df.id, df.procurement_id, df.queue_id, df.source_table,
                      df.source_id, q.contract_number, df.file_name, df.url,
                      df.url_hash, df.physical_download_key, df.download_status,
                      df.local_path, df.local_deleted_at
                 FROM document_files df
                 LEFT JOIN document_processing_queue q ON q.id = df.queue_id
                WHERE df.id=%s""",
            (doc_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--document-file-id", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--cleanup",
        action="store_true",
        help="удалить временную папку после скачивания (по умолчанию файлы сохраняются для reparse)",
    )
    args = ap.parse_args()

    conn = psycopg2.connect(**di_dsn())
    try:
        row = fetch(conn, args.document_file_id)
    finally:
        conn.close()
    if not row:
        print(f"NOT_FOUND document_file_id={args.document_file_id}")
        return 2
    print(
        f"doc_file_id={row['id']} pid={row['procurement_id']} queue={row['queue_id']} "
        f"status={row['download_status']} local={row['local_path']} deleted={row['local_deleted_at']}"
    )
    print(f"file_name={row['file_name']}")
    print(f"url={row['url']}")
    if not args.apply:
        print("DRY_RUN=YES (no download)")
        return 0
    if not row.get("url"):
        print("NO_URL=YES")
        return 2

    from document_processor.daemon import DocumentProcessorDaemon

    daemon = DocumentProcessorDaemon()
    downloader = daemon.downloader
    link = (
        row["url"],
        row["file_name"],
        row["id"],
        row.get("physical_download_key"),
    )
    try:
        res = downloader.download_and_extract(
            task_id=int(row["queue_id"]),
            links=[link],
            procurement_id=int(row["procurement_id"]),
            source_id=row.get("source_id"),
            table_source=row.get("source_table"),
            contract_number=row.get("contract_number"),
        )
        print(
            f"DOWNLOAD attempted={res.attempted_count} downloaded={res.downloaded_count} "
            f"failed={res.failed_count} skipped={res.skipped_count} rate_limited={res.rate_limited}"
        )
        for path in res.files:
            print(f"  FILE {path} exists={path.exists()}")
        for failure in res.failures:
            print(
                f"  FAIL class={failure.error_class} http={failure.http_status} "
                f"msg={failure.error_message[:200]}"
            )
    finally:
        if args.cleanup:
            try:
                downloader.cleanup(int(row["queue_id"]))
            except Exception as exc:  # noqa: BLE001
                print(f"CLEANUP_WARN={exc}")
        else:
            print("KEEP_FILES=YES (cleanup skipped; run with --cleanup after reparse)")

    conn = psycopg2.connect(**di_dsn())
    try:
        after = fetch(conn, args.document_file_id)
    finally:
        conn.close()
    if after:
        exists = bool(after.get("local_path")) and Path(after["local_path"]).exists()
        print(
            f"AFTER status={after['download_status']} local={after['local_path']} "
            f"deleted={after['local_deleted_at']} exists={exists}"
        )
    return 0 if after and after.get("local_path") and Path(after["local_path"]).exists() else 1


if __name__ == "__main__":
    raise SystemExit(main())
