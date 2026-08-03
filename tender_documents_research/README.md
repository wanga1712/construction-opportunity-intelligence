# tender_documents_research — карта модулей

Сервер 13 (sergey / 10.8.0.13). Обрабатывает документы из очереди document_processing_queue на сервере 7.

## Статус (2026-08-03) — ошибок нет, работает штатно

| Параметр | Значение |
|---|---|
| Демонов активно | 5 (worker 13,14,15,16,17) |
| Pending в очереди | 538 |
| Completed всего | 252 |
| No links | 2550 |
| Sales window expired | 1789 |
| Classifier кеш | 8382 контрактов |
| DNS | исправлен (static /etc/resolv.conf 8.8.8.8) |
| Авто-выключение | 23:00 (root crontab) |

## Изменения (2026-08-03)

- **DNS исправлен**: убран симлинк systemd-resolved, статический resolv.conf 8.8.8.8/8.8.4.4/1.1.1.1
- **Race condition в очереди устранён**: UNIQUE INDEX uq_dpq_contract + ON CONFLICT DO NOTHING в queue_manager.py (было 88 дублей)
- **600 DNS-провальных контрактов** возвращены в pending (weekend DNS outage)
- **54 мусорных термина удалены** из crm_product_subcategory_terms (тип зданий/локаций — не продукты)
- **temp_shutdown_guard.sh** переписан: psql → Python psycopg2 (psql не установлен на сервере 13)
- **Мониторинг-страница CRM** полностью переписана с аналитикой (очередь, throughput, ETA, ошибки)
- **Классификатор подтверждён**: НЕ скипает контракты — только передаёт priority scores (0-10) в matcher

## Модули

| Модуль | Назначение | README |
|---|---|---|
| daemon | Главный цикл: захват задач, скачивание, обработка | docs/modules/daemon/README.md |
| contract_classifier | LLM pre-classifier (Ollama qwen2.5:7b), оценки 0-10 для 11 категорий | docs/modules/contract_classifier/README.md |
| matcher | Поиск ключевых слов в тексте, fuzzy/exact/lite-mode | docs/modules/matcher/README.md |
| task_pipeline | Оркестратор: classifier → downloader → extractor → matcher | docs/modules/task_pipeline/README.md |
| queue_manager | Захват задач из БД (SKIP LOCKED), смена статусов | docs/modules/queue_manager/README.md |

## Сервисы systemd

| Сервис | worker_id | Источник |
|---|---|---|
| tender-docs-daemon-open | 13 | reestr_contract_44_fz, reestr_contract_223_fz |
| tender-docs-daemon-open-2 | 15 | reestr_contract_44_fz, reestr_contract_223_fz |
| tender-docs-daemon-open-3 | 16 | reestr_contract_44_fz, reestr_contract_223_fz |
| tender-docs-daemon-awarded | 14 | reestr_contract_44_fz_awarded |
| tender-docs-daemon-awarded-2 | 17 | reestr_contract_44_fz_awarded |

Env файлы:  и 

## БД

PostgreSQL на 10.8.0.7, база . Таблицы: docs/database/tables/

## Архив старых документов

docs/archive/ — устаревшие AUDIT_*, STATUS_*, SUMMARY_* файлы

## Что нужно сделать

- CRM: UI настройки категорий классификатора
- docs/modules/ — наполнить READMEs фактическими данными
- UUID миграция ключей (риск потери ссылок)
- Self-learning демоны (README_analytical_daemons.md раздел 15)
