# daemon — главный рабочий цикл

Файл: document_processor/daemon.py  
Запуск: python -m document_processor.daemon  
Сервисы: tender-docs-daemon-open, tender-docs-daemon-open-2, tender-docs-daemon-open-3, tender-docs-daemon-awarded, tender-docs-daemon-awarded-2

## Что делает

1. populate_queue() — добавляет новые контракты из реестров в document_processing_queue
2. get_next_batch() — захватывает N задач (SKIP LOCKED, атомарно)
3. pending_future — скачивает следующий пакет пока обрабатывается текущий
4. Для каждой задачи: contract_classifier → download → extract text → matcher
5. Consecutive errors: 3 ошибки скачивания подряд → запись в daemon_alerts

## Параметры (env)

WORKER_ID, QUEUE_TABLE_SOURCES, BATCH_SIZE, DAEMON_SLEEP_SECONDS, DOCUMENT_DOWNLOAD_DIR, QUEUE_POPULATE_LIMIT, CLASSIFIER_SKIP_THRESHOLD=1, CLASSIFIER_LITE_THRESHOLD=4

## Алерты и мониторинг

Таблица daemon_alerts (на БД сервера 7). CRM показывает их в infrastructure_page.py.
