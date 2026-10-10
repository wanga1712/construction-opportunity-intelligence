"""Принудительный прогон документного контура по конкретным закупкам (очередь вне DWRR-порядка).

Берём строки очереди, помеченные `last_error = 'requeue:direct_missing_files'`
(их ставит scripts/requeue_direct_missing_documents.py), и прогоняем по одной через тот же
путь, что и демон (`DocumentProcessorDaemon._process_s13v2_task`), но с force_contract —
поэтому 25k чужих PENDING-строк их не задерживают.

Запуск — интерпретатором воркерного venv и с теми же EnvironmentFile, что у демонов
(в /etc/tender-docs-db.env лежат credentials S7, файл root-only):

    sudo -n systemd-run --pipe --wait --uid=sergey --gid=sergey \
        --property=WorkingDirectory=/opt/tender_documents_research \
        --property=EnvironmentFile=/opt/tender_documents_research/.env \
        --property=EnvironmentFile=/etc/tender-docs-db.env \
        --property=EnvironmentFile=/etc/tender-docs-worker-open.env \
        --property=Environment=FORCE_BATCH=5 \
        /opt/tender_documents_research/.venv/bin/python /opt/CRM_Streamlit/scripts/force_direct_documents.py
"""
from __future__ import annotations

import os
import sys
import time

MARK = os.getenv("FORCE_MARK", "requeue:direct_missing_files")
BATCH = int(os.getenv("FORCE_BATCH", "5"))
WORKER_ID = int(os.getenv("FORCE_WORKER_ID", "77"))


def pending_contracts(queue) -> list:
    """Контракты, помеченные нашей переочередью и ждущие обработки."""
    conn = queue._get_conn()  # noqa: SLF001 - служебный прогон на своей же БД
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT contract_number FROM document_processing_queue
                   WHERE status = 'PENDING' AND last_error = %s
                     AND contract_number IS NOT NULL
                   ORDER BY id LIMIT %s""",
                (MARK, BATCH),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    from document_processor.daemon import DocumentProcessorDaemon

    daemon = DocumentProcessorDaemon()
    contracts = pending_contracts(daemon.s13_backend.queue)
    print("force_run: contracts=%d worker_id=%d mark=%s" % (len(contracts), WORKER_ID, MARK),
          flush=True)
    if not contracts:
        print("нечего обрабатывать")
        return 0
    done = failed = 0
    for contract in contracts:
        started = time.time()
        tasks = daemon.s13_backend.queue.claim_batch(
            worker_id=WORKER_ID, batch_size=1, force_contract=contract)
        if not tasks:
            print("SKIP %s (не удалось захватить строку)" % contract, flush=True)
            continue
        for task in tasks:
            try:
                daemon._process_s13v2_task(task)  # noqa: SLF001 - штатный путь демона
                done += 1
                print("OK %s (%.1fs)" % (contract, time.time() - started), flush=True)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("FAIL %s: %s" % (contract, exc), flush=True)
    print("force_run done: ok=%d fail=%d" % (done, failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
