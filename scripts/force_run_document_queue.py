#!/usr/bin/env python3
"""Force-run specific document_processing_queue rows outside the DWRR claim order.

Targeted re-runs (e.g. validating a pipeline change on a planned row) where the
normal claim order would push the row back. Processes through the same code path
as the daemon: `DocumentProcessorDaemon._process_s13v2_task`.

    --queue-id 90595[,148931]     explicit queue ids (resolved to contract+table)

Run with the worker venv and the daemon EnvironmentFiles, e.g.:

    sudo -n systemd-run --unit=force-run-1b-99069 --collect \
        --uid=sergey --gid=sergey \
        --property=WorkingDirectory=/opt/tender_documents_research \
        --property=EnvironmentFile=/opt/tender_documents_research/.env \
        --property=EnvironmentFile=/etc/tender-docs-db.env \
        --property=EnvironmentFile=/etc/tender-docs-worker-open.env \
        /opt/tender_documents_research/.venv/bin/python \
        /opt/CRM_Streamlit/scripts/force_run_document_queue.py --queue-id 90595
"""
from __future__ import annotations

import argparse
import os
import time

WORKER_ID = int(os.getenv("FORCE_WORKER_ID", "77"))


def _lookup(queue, queue_ids):
    conn = queue._get_conn()  # noqa: SLF001 - служебный прогон на своей же БД
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, contract_number, source_table
                     FROM document_processing_queue WHERE id = ANY(%s)""",
                (list(queue_ids),),
            )
            return {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue-id", required=True, help="comma-separated queue ids")
    args = ap.parse_args()
    queue_ids = [int(x) for x in args.queue_id.split(",") if x.strip()]

    from document_processor.daemon import DocumentProcessorDaemon

    daemon = DocumentProcessorDaemon()
    queue = daemon.s13_backend.queue
    targets = _lookup(queue, queue_ids)

    ok = fail = 0
    for qid in queue_ids:
        if qid not in targets:
            print("MISSING queue_id=%s" % qid, flush=True)
            fail += 1
            continue
        contract, table = targets[qid]
        if not contract:
            print("NO_CONTRACT queue_id=%s" % qid, flush=True)
            fail += 1
            continue
        started = time.time()
        tasks = queue.claim_batch(
            worker_id=WORKER_ID, batch_size=1,
            force_contract=contract, force_table=table,
        )
        if not tasks:
            print("SKIP queue_id=%s (не удалось захватить)" % qid, flush=True)
            fail += 1
            continue
        for task in tasks:
            if int(task.get("id")) != qid:
                print("MISMATCH queue_id=%s claimed=%s -> release"
                      % (qid, task.get("id")), flush=True)
                queue.mark_pending(int(task.get("id")), "force_run:not_target")
                fail += 1
                continue
            try:
                daemon._process_s13v2_task(task)  # noqa: SLF001 - штатный путь демона
                ok += 1
                print("OK queue_id=%s (%.1fs)" % (qid, time.time() - started), flush=True)
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print("FAIL queue_id=%s: %s" % (qid, exc), flush=True)
    print("force_run done: ok=%d fail=%d" % (ok, fail), flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
