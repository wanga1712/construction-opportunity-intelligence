# queue_manager — управление очередью

Файл: document_processor/queue_manager.py

## Таблица document_processing_queue (на БД сервера 7)

Колонки: id, contract_reg_number, table_source, status, worker_id, started_at, completed_at, error_message, created_at, user_id, priority

## Статусы

pending → processing → completed / no_links / error / sales_window_expired

## Захват задач

claim_batch_ids() — использует SELECT FOR UPDATE SKIP LOCKED.
Несколько воркеров с разными WORKER_ID не пересекаются.

## Автоматика

- requeue_error_tasks() — вызывается в цикле демона
- /usr/local/bin/requeue_no_links.sh — cron 06:00 на сервере 7
