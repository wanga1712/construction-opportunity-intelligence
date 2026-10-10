"""Принудительная переочередь закупок прямых поставок, у которых документы удалены retention'ом.

Зачем: retention удаляет файлы после разбора («разобрали → удаляем»), поэтому у части
DIRECT-закупок на диске не остаётся ни одного документа и карточка показывает пустые
смету/требования. Очередь уже COMPLETED и сама повторно не пойдёт, поэтому строки нужно
вернуть в PENDING: даунлоадер при повторном прогоне видит, что файл помечен COMPLETED, но
локально отсутствует, и перекачивает его (downloader._process_single_link).

Работаем только с очередью: ссылки резолвятся в момент скачивания
(DocumentationLinksLoader по contract_number), в S13 ссылки не дублируются.

usage:
    python scripts/requeue_direct_missing_documents.py                 # dry-run
    python scripts/requeue_direct_missing_documents.py --apply --limit 40
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

REQUEUE_MARK = "requeue:direct_missing_files"
REQUEUEABLE = ("COMPLETED", "FAILED", "NO_LINKS", "SKIPPED_NOT_TARGET", "SKIPPED_NOISE")


def _conn(dbname: str):
    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["dbname"] = dbname
    kwargs.setdefault("connect_timeout", 10)
    return psycopg2.connect(**kwargs)


def direct_pids(crm) -> List[int]:
    with crm.cursor() as cur:
        cur.execute(
            """SELECT procurement_id FROM crm_procurement_category_opportunities
               WHERE upper(coalesce(opportunity_track, '')) = 'DIRECT_SUPPLY'
               GROUP BY procurement_id"""
        )
        return [row[0] for row in cur.fetchall()]


def missing_files(di, pids: List[int]) -> Dict[int, Tuple[int, int]]:
    """pid -> (всего файлов, отсутствует на диске)."""
    out: Dict[int, Tuple[int, int]] = {}
    with di.cursor() as cur:
        cur.execute(
            """SELECT procurement_id, local_path, local_deleted_at
               FROM document_files
               WHERE procurement_id = ANY(%s) AND local_path IS NOT NULL""",
            (pids,),
        )
        rows = cur.fetchall()
    total: Dict[int, int] = {}
    present: Dict[int, int] = {}
    for pid, path, purged in rows:
        total[pid] = total.get(pid, 0) + 1
        if path and not purged and os.path.exists(path):
            present[pid] = present.get(pid, 0) + 1
    for pid, count in total.items():
        out[pid] = (count, count - present.get(pid, 0))
    return out


def queue_rows(di, pids: List[int]) -> List[Dict[str, Any]]:
    with di.cursor() as cur:
        cur.execute(
            """SELECT id, procurement_id, status, contract_number, source_table
               FROM document_processing_queue
               WHERE procurement_id = ANY(%s)""",
            (pids,),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="выполнить изменения (по умолчанию dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="максимум закупок за прогон")
    parser.add_argument("--partial", action="store_true",
                        help="брать и закупки, где часть файлов ещё на диске")
    args = parser.parse_args()

    crm = _conn(os.getenv("CRM_DB_DATABASE", "crm"))
    try:
        pids = direct_pids(crm)
    finally:
        crm.close()
    di = _conn(os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"))
    try:
        files = missing_files(di, pids)
        targets = [pid for pid, (total, miss) in files.items()
                   if total and miss and (miss if args.partial else miss == total)]
        targets.sort()
        rows = queue_rows(di, targets)
        rows.sort(key=lambda row: row["procurement_id"])
        if args.limit:
            rows = rows[:args.limit]
        by_status: Dict[str, int] = {}
        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        ids = [row["id"] for row in rows if row["status"] in REQUEUEABLE]
        skipped = sorted({row["status"] for row in rows if row["status"] not in REQUEUEABLE})
        print("direct_pids=%d pids_without_files=%d pids_in_batch=%d" % (
            len(pids), len(targets), len({row["procurement_id"] for row in rows})))
        print("queue statuses: %s" % by_status)
        print("requeue_candidates=%d, пропускаем статусы: %s" % (len(ids), skipped or "нет"))
        print("пример закупок: %s" % sorted({row["procurement_id"] for row in rows})[:10])
        if not args.apply:
            print("DRY-RUN: изменения не применены (добавь --apply)")
            return 0
        if not ids:
            print("нечего переочередить")
            return 0
        with di.cursor() as cur:
            cur.execute(
                """UPDATE document_processing_queue
                      SET status='PENDING', worker_id=NULL, started_at=NULL, last_error=%s
                    WHERE id = ANY(%s)""",
                (REQUEUE_MARK, ids),
            )
            updated = cur.rowcount
        di.commit()
        print("APPLIED: %d строк очереди → PENDING (%s)" % (updated, REQUEUE_MARK))
    finally:
        di.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
